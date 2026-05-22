"""
Clustering module — Phase 3.
POST /cluster/run : Run HDBSCAN on all unmatched face embeddings.
GET /clusters     : List active (non-ignored, non-promoted) clusters.
POST /clusters/{id}/ignore   : Mark cluster as noise (ignored=true).
DELETE /clusters/{id}/ignore : Restore cluster (ignored=false).
POST /clusters/{id}/promote  : Bulk-update member face_detections → known person.
"""
import asyncio
import logging
from collections import Counter
from typing import Optional
from uuid import UUID, uuid4

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sklearn.cluster import HDBSCAN

from . import config
from .db import get_pool
from .storage import get_minio_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["clustering"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class ClusterRunResponse(BaseModel):
    clusters_created: int
    clusters_updated: int
    faces_assigned:   int


class ClusterResponse(BaseModel):
    id:                      str
    representative_frame_id: Optional[int]
    appearance_count:        int
    first_seen:              Optional[str]
    last_seen:               Optional[str]
    thumbnail_url:           Optional[str]
    ignored:                 bool
    label:                   Optional[str] = None


class ClusterLabelRequest(BaseModel):
    label: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: pick representative face (best det_score × sharpness)
# ─────────────────────────────────────────────────────────────────────────────

async def _pick_representative_face(conn, face_ids: list[int], minio_client) -> Optional[int]:
    """
    Return face_detection.id for the best representative of a cluster.
    Strategy: fetch top 3 by det_score, compute Laplacian sharpness on frame image,
    return face with highest det_score × normalized_sharpness.
    Falls back to highest det_score alone if MinIO fetch fails for all candidates.
    """
    rows = await conn.fetch("""
        SELECT fd.id, fd.det_score, f.minio_key
        FROM face_detections fd
        JOIN frames f ON f.id = fd.frame_id
        WHERE fd.id = ANY($1::bigint[])
        ORDER BY fd.det_score DESC
        LIMIT 3
    """, face_ids)

    if not rows:
        return None

    best_face_id: Optional[int] = None
    best_score: float = -1.0
    loop = asyncio.get_running_loop()

    for row in rows:
        det_score = float(row["det_score"] or 0.0)
        minio_key = row["minio_key"]

        if not minio_key:
            if det_score > best_score:
                best_score = det_score
                best_face_id = row["id"]
            continue

        try:
            response = await loop.run_in_executor(
                None,
                lambda key=minio_key: minio_client.get_object(config.MINIO_BUCKET_FRAMES, key),
            )
            img_bytes = response.read()
            response.close()
            response.release_conn()
        except Exception as exc:
            logger.warning("MinIO fetch failed for face %s (key=%s): %s", row["id"], minio_key, exc)
            # Fallback: use det_score only
            if det_score > best_score:
                best_score = det_score
                best_face_id = row["id"]
            continue

        # Variance of Laplacian — higher = sharper
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            if det_score > best_score:
                best_score = det_score
                best_face_id = row["id"]
            continue

        sharpness = float(cv2.Laplacian(img, cv2.CV_64F).var())
        combined = det_score * min(sharpness / 100.0, 1.0)
        if combined > best_score:
            best_score = combined
            best_face_id = row["id"]

    return best_face_id


# ─────────────────────────────────────────────────────────────────────────────
# POST /cluster/run
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/cluster/run", response_model=ClusterRunResponse)
async def run_clustering() -> ClusterRunResponse:
    """
    Run HDBSCAN on all unmatched face embeddings. Idempotent.

    Algorithm: sklearn HDBSCAN with kd_tree (euclidean metric).
    NOTE: sklearn uses algorithm='kd_tree', NOT 'boruvka_kdtree' (standalone hdbscan package name).

    Stable UUID strategy: for each HDBSCAN cluster, take majority vote of
    existing unknown_cluster_id values from member face_detections. If no
    existing UUID → new uuid4(). This preserves cluster identity across re-runs.
    """
    pool = await get_pool()
    minio_client = get_minio_client()

    # ── Step 1: Load unmatched embeddings ────────────────────────────────────
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                fd.id,
                fd.normed_embedding,
                fd.unknown_cluster_id::text,
                fd.det_score,
                COALESCE(v.recorded_at, v.ingested_at) AS frame_ts
            FROM face_detections fd
            JOIN frames fr ON fr.id = fd.frame_id
            JOIN videos v  ON v.id  = fr.video_id
            WHERE fd.matched_person_id IS NULL
              AND fd.normed_embedding IS NOT NULL
        """)

    if len(rows) < config.CLUSTER_MIN_SIZE:
        logger.info("Not enough unmatched faces (%d) for clustering (min=%d)",
                    len(rows), config.CLUSTER_MIN_SIZE)
        return ClusterRunResponse(clusters_created=0, clusters_updated=0, faces_assigned=0)

    face_ids             = [r["id"] for r in rows]
    existing_cluster_ids = [r["unknown_cluster_id"] for r in rows]   # may be None
    X = np.array([r["normed_embedding"] for r in rows], dtype=np.float32)

    # ── Step 2: HDBSCAN ───────────────────────────────────────────────────────
    # algorithm='kd_tree' is the sklearn equivalent of boruvka_kdtree (standalone pkg).
    # n_jobs=1: single-threaded — i5-6200 8GB RAM constraint.
    clusterer = HDBSCAN(
        min_cluster_size=config.CLUSTER_MIN_SIZE,
        min_samples=config.CLUSTER_MIN_SAMPLES,
        metric="euclidean",
        algorithm="kd_tree",
        n_jobs=1,
    )
    labels: np.ndarray = clusterer.fit_predict(X)   # label=-1 = noise

    # ── Step 3: Map HDBSCAN labels → stable UUIDs (majority vote) ────────────
    label_to_uuid: dict[int, str] = {}
    label_face_ids: dict[int, list[int]] = {}

    for i, label in enumerate(labels):
        if label == -1:
            continue
        label_face_ids.setdefault(int(label), []).append(face_ids[i])

    for hdbscan_label, member_face_ids in label_face_ids.items():
        indices = [i for i, lbl in enumerate(labels) if int(lbl) == hdbscan_label]
        existing = [existing_cluster_ids[i] for i in indices if existing_cluster_ids[i]]
        if existing:
            label_to_uuid[hdbscan_label] = Counter(existing).most_common(1)[0][0]
        else:
            label_to_uuid[hdbscan_label] = str(uuid4())

    if not label_to_uuid:
        logger.info("HDBSCAN produced only noise — no clusters to write")
        return ClusterRunResponse(clusters_created=0, clusters_updated=0, faces_assigned=0)

    # ── Step 4: Compute per-cluster stats + pick representative ───────────────
    cluster_rows_map: dict[str, list] = {uuid: [] for uuid in label_to_uuid.values()}
    for i, label in enumerate(labels):
        if int(label) == -1:
            continue
        cluster_uuid = label_to_uuid[int(label)]
        cluster_rows_map[cluster_uuid].append(rows[i])

    upsert_params: list[tuple] = []

    async with pool.acquire() as conn:
        for cluster_uuid, member_rows in cluster_rows_map.items():
            appearance_count = len(member_rows)
            frame_ts_list = [r["frame_ts"] for r in member_rows if r["frame_ts"]]
            first_seen = min(frame_ts_list) if frame_ts_list else None
            last_seen  = max(frame_ts_list) if frame_ts_list else None
            member_face_ids = [r["id"] for r in member_rows]

            rep_face_id = await _pick_representative_face(conn, member_face_ids, minio_client)

            upsert_params.append((
                cluster_uuid,    # $1 id
                rep_face_id,     # $2 representative_face_id
                appearance_count,# $3
                first_seen,      # $4
                last_seen,       # $5
            ))

    # ── Step 5: UPSERT unknown_clusters ──────────────────────────────────────
    existing_uuids: set[str] = set(u for u in existing_cluster_ids if u)
    clusters_created = 0
    clusters_updated = 0

    async with pool.acquire() as conn:
        for params in upsert_params:
            cluster_uuid = params[0]
            await conn.execute("""
                INSERT INTO unknown_clusters
                    (id, representative_face_id, appearance_count, first_seen, last_seen)
                VALUES ($1::uuid, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    representative_face_id = EXCLUDED.representative_face_id,
                    appearance_count       = EXCLUDED.appearance_count,
                    first_seen             = EXCLUDED.first_seen,
                    last_seen              = EXCLUDED.last_seen
            """, *params)

            if cluster_uuid in existing_uuids:
                clusters_updated += 1
            else:
                clusters_created += 1

        # ── Step 6: Bulk UPDATE face_detections.unknown_cluster_id ───────────
        # First, clear stale assignments for all currently-unmatched faces.
        await conn.execute("""
            UPDATE face_detections
            SET unknown_cluster_id = NULL
            WHERE matched_person_id IS NULL
        """)

        # Then assign current cluster UUIDs.
        updates = [
            (label_to_uuid[int(labels[i])], face_ids[i])
            for i in range(len(face_ids))
            if int(labels[i]) != -1
        ]
        await conn.executemany(
            "UPDATE face_detections SET unknown_cluster_id = $1::uuid WHERE id = $2",
            updates,
        )

    faces_assigned = len(updates)
    logger.info(
        "Clustering complete: %d created, %d updated, %d faces assigned",
        clusters_created, clusters_updated, faces_assigned,
    )
    return ClusterRunResponse(
        clusters_created=clusters_created,
        clusters_updated=clusters_updated,
        faces_assigned=faces_assigned,
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /clusters
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/clusters", response_model=list[ClusterResponse])
async def list_clusters(include_ignored: bool = False) -> list[ClusterResponse]:
    """
    Return clusters that have not been promoted to a known person.
    include_ignored=False (default): only active clusters (ignored=false).
    include_ignored=True: only ignored clusters (ignored=true) — for the UI collapsed section.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                uc.id::text,
                uc.appearance_count,
                uc.first_seen::text,
                uc.last_seen::text,
                uc.ignored,
                uc.label,
                fd.frame_id AS representative_frame_id
            FROM unknown_clusters uc
            LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id
            WHERE uc.promoted_at IS NULL
              AND uc.ignored = $1
            ORDER BY uc.appearance_count DESC
        """, include_ignored)

    return [
        ClusterResponse(
            id=r["id"],
            representative_frame_id=r["representative_frame_id"],
            appearance_count=r["appearance_count"],
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
            thumbnail_url=(
                f"/frames/{r['representative_frame_id']}/image"
                if r["representative_frame_id"] else None
            ),
            ignored=r["ignored"],
            label=r["label"],
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# POST /clusters/{cluster_id}/ignore  — mark as noise
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/clusters/{cluster_id}/ignore", status_code=status.HTTP_200_OK)
async def ignore_cluster(cluster_id: UUID) -> dict:
    """Set ignored=true. Cluster disappears from default GET /clusters."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET ignored = true WHERE id = $1",
            cluster_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "ignored": True}


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /clusters/{cluster_id}/ignore  — restore from ignored
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/clusters/{cluster_id}/ignore", status_code=status.HTTP_200_OK)
async def restore_cluster(cluster_id: UUID) -> dict:
    """Set ignored=false. Cluster reappears in default GET /clusters."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET ignored = false WHERE id = $1",
            cluster_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "ignored": False}


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /clusters/{cluster_id}/label  — set or clear freeform nickname
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/clusters/{cluster_id}/label", status_code=status.HTTP_200_OK)
async def set_cluster_label(cluster_id: UUID, body: ClusterLabelRequest) -> dict:
    """Set or clear the freeform nickname for a cluster. Empty string → null."""
    label = body.label.strip() if body.label else None
    if label and len(label) > 100:
        raise HTTPException(status_code=422, detail="label must be ≤ 100 characters")
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET label = $1 WHERE id = $2",
            label,
            cluster_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "label": label}
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/clusters/{cluster_id}/promote", status_code=status.HTTP_200_OK)
async def promote_cluster(cluster_id: UUID, person_id: UUID) -> dict:
    """
    Bulk-update all member face_detections to matched_person_id=person_id.
    Sets match_tier='confident' and match_similarity=1.0 (per Phase 1 schema).
    Sets promoted_at=now() on the cluster row — cluster disappears from GET /clusters.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Verify cluster exists
        row = await conn.fetchrow(
            "SELECT id FROM unknown_clusters WHERE id = $1", cluster_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Cluster not found")

        # Bulk update member face_detections
        result = await conn.execute("""
            UPDATE face_detections
            SET matched_person_id = $1::uuid,
                match_tier        = 'confident',
                match_similarity  = 1.0
            WHERE unknown_cluster_id = $2::uuid
              AND matched_person_id IS NULL
        """, person_id, cluster_id)

        matched = int(result.split()[-1])   # "UPDATE N" → N

        # Mark cluster as promoted
        await conn.execute(
            "UPDATE unknown_clusters SET promoted_at = now() WHERE id = $1::uuid",
            cluster_id,
        )

    logger.info(
        "Promoted cluster %s → person %s (%d faces updated)",
        cluster_id, person_id, matched,
    )
    return {
        "cluster_id": str(cluster_id),
        "person_id":  str(person_id),
        "matched":    matched,
    }
