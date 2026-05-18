"""
Person enrollment router.
Endpoints:
    POST   /persons                       — create known person
    GET    /persons                       — list all with enrollment count
    POST   /persons/{person_id}/enroll   — upload 1-N face images
    DELETE /persons/{person_id}          — delete person + embeddings (CASCADE)
    POST   /persons/{person_id}/rematch  — retroactively match face_detections
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from . import config
from .db import get_pool
from .faces_api import analyze_image_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persons", tags=["persons"])

# ── Max upload size guard ─────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB per image

# ── Pydantic models ───────────────────────────────────────────────────────────

class CreatePersonRequest(BaseModel):
    name: str
    notes: Optional[str] = None


class PersonResponse(BaseModel):
    id: str
    name: str
    notes: Optional[str]
    created_at: str
    enrollment_count: int = 0


class EnrollResponse(BaseModel):
    person_id: str
    enrolled: int
    rejected: list[dict]
    warning: Optional[str] = None


class RematchResponse(BaseModel):
    person_id: str
    matched: int


# ── POST /persons ─────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED, response_model=PersonResponse)
async def create_person(body: CreatePersonRequest) -> PersonResponse:
    """Create a known person record. Name must be unique."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO known_persons (name, notes)
                VALUES ($1, $2)
                RETURNING id::text, name, notes, created_at::text
                """,
                body.name,
                body.notes,
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A person named '{body.name}' already exists",
                )
            raise
    return PersonResponse(
        id=row["id"],
        name=row["name"],
        notes=row["notes"],
        created_at=row["created_at"],
        enrollment_count=0,
    )


# ── GET /persons ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[PersonResponse])
async def list_persons() -> list[PersonResponse]:
    """List all known persons with their embedding count."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                kp.id::text,
                kp.name,
                kp.notes,
                kp.created_at::text,
                COUNT(pe.id)::int AS enrollment_count
            FROM known_persons kp
            LEFT JOIN person_embeddings pe ON pe.person_id = kp.id
            GROUP BY kp.id, kp.name, kp.notes, kp.created_at
            ORDER BY kp.name
            """
        )
    return [
        PersonResponse(
            id=r["id"],
            name=r["name"],
            notes=r["notes"],
            created_at=r["created_at"],
            enrollment_count=r["enrollment_count"],
        )
        for r in rows
    ]


# ── POST /persons/{person_id}/enroll ─────────────────────────────────────────

@router.post("/{person_id}/enroll", response_model=EnrollResponse)
async def enroll_images(
    person_id: UUID,
    request: Request,
    images: list[UploadFile] = File(..., description="1–N enrollment photos"),
) -> EnrollResponse:
    """
    Upload 1–N face photos for a known person.
    Each image is validated:
      1. Decodable as an image by OpenCV
      2. Exactly one face detected
      3. det_score >= 0.70
      4. Bounding box >= 80×80 px
      5. File size <= 10 MB
    Accepted images are inserted into person_embeddings even if some are rejected.
    A warning is returned when total enrolled count (all-time) < 5.
    """
    face_app = request.app.state.face_app

    # Verify person exists
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    enrolled_this_call: list[dict] = []
    rejected: list[dict] = []

    for img_file in images:
        fname = img_file.filename or "upload"
        data = await img_file.read()

        # Gate 0: file size
        if len(data) > MAX_UPLOAD_BYTES:
            rejected.append({"filename": fname, "reason": f"File exceeds 10 MB limit"})
            continue

        # Gate 1: decodable image
        faces = analyze_image_bytes(data, face_app)
        if not isinstance(faces, list) or (len(faces) == 0 and len(data) > 0):
            # analyze_image_bytes returns [] for invalid images
            # distinguish "no face" from "bad image" by re-checking decode
            import cv2, numpy as np
            arr = np.frombuffer(data, dtype=np.uint8)
            if cv2.imdecode(arr, cv2.IMREAD_COLOR) is None:
                rejected.append({"filename": fname, "reason": "Not a valid image"})
                continue
            rejected.append({"filename": fname, "reason": "No face detected"})
            continue

        # Gate 2: exactly one face
        if len(faces) == 0:
            rejected.append({"filename": fname, "reason": "No face detected"})
            continue
        if len(faces) > 1:
            rejected.append({
                "filename": fname,
                "reason": f"Multiple faces ({len(faces)}) detected — upload a solo photo",
            })
            continue

        face = faces[0]

        # Gate 3: detector confidence
        if face["det_score"] < 0.70:
            rejected.append({
                "filename": fname,
                "reason": f"Face has low detector confidence ({face['det_score']:.2f}) — use a clearer photo",
            })
            continue

        # Gate 4: bounding box minimum size
        w = face["bbox_x2"] - face["bbox_x1"]
        h = face["bbox_y2"] - face["bbox_y1"]
        if w < 80 or h < 80:
            rejected.append({
                "filename": fname,
                "reason": f"Face is too small ({w}×{h}px) — use a closer photo",
            })
            continue

        enrolled_this_call.append({
            "filename": fname,
            "normed_embedding": face["normed_embedding"],
        })

    # Bulk-insert accepted embeddings
    if enrolled_this_call:
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO person_embeddings (person_id, normed_embedding, source_image)
                VALUES ($1::uuid, $2::vector, $3)
                """,
                [
                    (str(person_id), e["normed_embedding"], e["filename"])
                    for e in enrolled_this_call
                ],
            )

    # Total enrollment count (all-time, not just this call)
    async with pool.acquire() as conn:
        total_count = await conn.fetchval(
            "SELECT COUNT(*) FROM person_embeddings WHERE person_id = $1",
            person_id,
        )

    warning = None
    if total_count < 5:
        warning = (
            f"Only {total_count} image(s) enrolled. "
            "Recognition accuracy is reduced with fewer than 5 images."
        )

    return EnrollResponse(
        person_id=str(person_id),
        enrolled=len(enrolled_this_call),
        rejected=rejected,
        warning=warning,
    )


# ── DELETE /persons/{person_id} ───────────────────────────────────────────────

@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person(person_id: UUID) -> None:
    """
    Delete a known person and all their embeddings.
    Cascades automatically via ON DELETE CASCADE on person_embeddings.
    face_detections.matched_person_id is SET NULL on cascade.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM known_persons WHERE id = $1", person_id
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Person not found")


# ── POST /persons/{person_id}/rematch ─────────────────────────────────────────

@router.post("/{person_id}/rematch", response_model=RematchResponse)
async def rematch_person(person_id: UUID) -> RematchResponse:
    """
    Retroactively scan ALL unmatched face_detections and update any that
    now match this person's embeddings (using the HNSW index).

    Algorithm (Python loop — NOT a SQL CROSS JOIN, which skips the HNSW index):
      1. Load all normed_embeddings from person_embeddings for this person.
      2. For each embedding, query face_detections HNSW index (LIMIT 1000 per embedding).
      3. Collect best similarity per face_detection_id across all embeddings.
      4. Single executemany UPDATE for all matched face_detections.

    Only updates face_detections where matched_person_id IS NULL (no re-matching
    faces already assigned to another person).
    """
    pool = await get_pool()

    # Verify person exists
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    high = config.FACE_MATCH_HIGH_THRESHOLD  # 0.65
    low  = config.FACE_MATCH_LOW_THRESHOLD   # 0.50

    # Step 1: load all enrollment embeddings for this person
    async with pool.acquire() as conn:
        emb_rows = await conn.fetch(
            "SELECT id, normed_embedding FROM person_embeddings WHERE person_id = $1",
            person_id,
        )

    if not emb_rows:
        return RematchResponse(person_id=str(person_id), matched=0)

    # Step 2: for each enrollment embedding, find matching unmatched face_detections
    # Uses face_detections HNSW index (ORDER BY <=> LIMIT activates HNSW scan)
    candidate_matches: dict[int, float] = {}  # face_detection_id → best_similarity

    async with pool.acquire() as conn:
        for emb_row in emb_rows:
            matches = await conn.fetch(
                """
                SELECT id, 1.0 - (normed_embedding <=> $1::vector) AS similarity
                FROM face_detections
                WHERE matched_person_id IS NULL
                  AND normed_embedding <=> $1::vector <= $2
                ORDER BY normed_embedding <=> $1::vector
                LIMIT 1000
                """,
                emb_row["normed_embedding"],
                1.0 - low,   # distance <= (1 - low_threshold) → similarity >= low
            )
            for m in matches:
                fd_id = m["id"]
                sim   = float(m["similarity"])
                if sim > candidate_matches.get(fd_id, -1.0):
                    candidate_matches[fd_id] = sim

    if not candidate_matches:
        return RematchResponse(person_id=str(person_id), matched=0)

    # Step 3: single bulk UPDATE
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            UPDATE face_detections
            SET
                matched_person_id = $1::uuid,
                match_similarity   = $2,
                match_tier         = CASE WHEN $2 >= $3 THEN 'confident' ELSE 'probable' END
            WHERE id = $4
              AND matched_person_id IS NULL
            """,
            [
                (str(person_id), sim, high, fd_id)
                for fd_id, sim in candidate_matches.items()
            ],
        )

    logger.info(
        "Rematch person %s: %d face_detections updated",
        person_id, len(candidate_matches),
    )
    return RematchResponse(person_id=str(person_id), matched=len(candidate_matches))


# ── GET /persons/{person_id}/faces ────────────────────────────────────────────
# Append these models and endpoint after rematch_person() in persons.py

class PersonFaceResult(BaseModel):
    face_detection_id: int
    frame_id:          int
    video_id:          str
    ts_ms:             int
    match_tier:        Optional[str]
    match_similarity:  Optional[float]
    det_score:         Optional[float]
    thumbnail_url:     str    # /frames/{frame_id}/image


class PersonFacesResponse(BaseModel):
    person_id:  str
    results:    list[PersonFaceResult]
    pagination: dict


@router.get("/{person_id}/faces", response_model=PersonFacesResponse)
async def list_person_faces(
    person_id: UUID,
    page: int = 1,
    page_size: int = 20,
) -> PersonFacesResponse:
    """
    Paginated list of face_detections matched to this person.
    Returns frame context (video_id, ts_ms) and thumbnail URL for each face.
    """
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be >= 1")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page_size must be 1–100")

    pool = await get_pool()

    # Verify person exists
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    offset = (page - 1) * page_size

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM face_detections WHERE matched_person_id = $1",
            person_id,
        )
        rows = await conn.fetch(
            """
            SELECT
                fd.id   AS face_detection_id,
                fd.frame_id,
                f.video_id::text,
                f.ts_ms,
                fd.match_tier,
                fd.match_similarity,
                fd.det_score
            FROM face_detections fd
            JOIN frames f ON f.id = fd.frame_id
            WHERE fd.matched_person_id = $1
            ORDER BY f.ts_ms DESC
            LIMIT $2 OFFSET $3
            """,
            person_id,
            page_size,
            offset,
        )

    results = [
        PersonFaceResult(
            face_detection_id=r["face_detection_id"],
            frame_id=r["frame_id"],
            video_id=r["video_id"],
            ts_ms=r["ts_ms"],
            match_tier=r["match_tier"],
            match_similarity=float(r["match_similarity"]) if r["match_similarity"] else None,
            det_score=float(r["det_score"]) if r["det_score"] else None,
            thumbnail_url=f"/frames/{r['frame_id']}/image",
        )
        for r in rows
    ]

    return PersonFacesResponse(
        person_id=str(person_id),
        results=results,
        pagination={
            "page":      page,
            "page_size": page_size,
            "total":     int(total),
            "has_next":  (page * page_size) < int(total),
        },
    )
