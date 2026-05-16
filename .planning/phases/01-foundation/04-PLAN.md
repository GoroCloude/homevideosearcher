---
plan: "04 — Face Recognition"
phase: 1
wave: 4
depends_on:
  - "03"
files_modified:
  - services/ingestion-worker/app/faces.py
  - services/ingestion-worker/app/pipeline.py
  - services/ingestion-worker/app/main.py
autonomous: true
requirements:
  - FACE-01
  - FACE-02
  - FACE-03
  - FACE-04
  - FACE-05

must_haves:
  truths:
    - "InsightFace buffalo_l (SCRFD + ArcFace) is loaded once at startup, 2 seconds after YOLO — never per-frame"
    - "InsightFace only runs on frames where YOLO detected at least one 'person' — not on every frame"
    - "512-dim `normed_embedding` (face.normed_embedding, not face.embedding) is stored in face_detections"
    - "Two-tier threshold applied: ≥0.65 → match_tier='confident'; 0.50–0.65 → match_tier='probable'; <0.50 → NULL (unknown)"
    - "Unmatched faces (similarity <0.50 or no person_embeddings exist) stored with matched_person_id=NULL, match_tier=NULL"
    - "YOLO person detections and InsightFace face detections are stored independently in separate tables"
    - "Cosine search uses pgvector HNSW index on person_embeddings.normed_embedding"
  artifacts:
    - path: "services/ingestion-worker/app/faces.py"
      provides: "InsightFace wrapper: model loading + face analysis + pgvector matching"
      contains: "load_face_model"
    - path: "services/ingestion-worker/app/pipeline.py"
      provides: "Updated pipeline calling real InsightFace (stub replaced)"
      contains: "run_insightface"
    - path: "services/ingestion-worker/app/main.py"
      provides: "Updated lifespan loading real InsightFace model with 2-second delay"
      contains: "face_app.prepare"
  key_links:
    - from: "services/ingestion-worker/app/main.py lifespan (asyncio.sleep(2))"
      to: "services/ingestion-worker/app/faces.py load_face_model()"
      via: "app.state.face_app = load_face_model() after 2-second sleep"
      pattern: "load_face_model"
    - from: "services/ingestion-worker/app/pipeline.py run_insightface()"
      to: "services/ingestion-worker/app/faces.py analyze_frame()"
      via: "direct function call"
      pattern: "analyze_frame"
    - from: "services/ingestion-worker/app/faces.py match_face_embedding()"
      to: "person_embeddings table (HNSW index)"
      via: "pgvector cosine search: normed_embedding <=> $1::vector"
      pattern: "normed_embedding <=> "
---

# Plan 04: Face Recognition

## Goal

Replace the `run_insightface()` stub in `pipeline.py` with real InsightFace buffalo_l inference. Implement `faces.py` with: model loading, full-frame SCRFD face detection, ArcFace 512-dim normed embedding, pgvector HNSW cosine search against `person_embeddings`, and two-tier threshold application. Update `main.py` to load the real model 2 seconds after YOLO.

---

## Tasks

<task id="04.1">
<title>Create faces.py — InsightFace model loading, frame analysis, and pgvector matching</title>
<read_first>
- requirements.md §6.1 (InsightFace usage pattern: FaceAnalysis buffalo_l, CPUExecutionProvider, normed_embedding)
- .planning/research/PITFALLS.md §FR-1 (two-tier threshold — use 0.65/0.50, not single 0.5), §FR-3 (run on full frame not YOLO crop), §FR-4 (normed_embedding not embedding — use face.normed_embedding exclusively)
- .planning/research/STACK.md §2 (InsightFace buffalo_l: SCRFD-10G detector + R100 ArcFace, ~280 MB, Python 3.11 only)
- .planning/research/SUMMARY.md §Critical Design Decisions §1 (two-tier table with exact thresholds)
- services/ingestion-worker/app/config.py (FACE_MATCH_HIGH_THRESHOLD=0.65, FACE_MATCH_LOW_THRESHOLD=0.50)
- services/ingestion-worker/app/pipeline.py (FaceDetection dataclass — must match exactly)
- db/init/001_schema.sql (person_embeddings table: normed_embedding column; HNSW index params)
</read_first>
<action>
Create `services/ingestion-worker/app/faces.py`:

```python
"""
InsightFace face recognition wrapper.

Key constraints (do not violate):
1. Model is loaded ONCE at startup (load_face_model). Never re-loaded per frame.
2. Always use face.normed_embedding (NOT face.embedding) — L2-normalized 512-dim vector.
3. Run InsightFace on the FULL FRAME (not YOLO person crops) — SCRFD handles detection.
4. YOLO and InsightFace run SEQUENTIALLY — this function is never called in parallel.
5. Two-tier threshold:
   - similarity >= FACE_MATCH_HIGH_THRESHOLD (0.65) → match_tier = 'confident'
   - FACE_MATCH_LOW_THRESHOLD (0.50) <= similarity < 0.65 → match_tier = 'probable'
   - similarity < FACE_MATCH_LOW_THRESHOLD (0.50) → matched_person_id = NULL, match_tier = NULL
6. Faces with no match (or no known persons enrolled) are stored with matched_person_id=NULL.
   These are the "unknown pool" that Phase 3 HDBSCAN clustering consumes.
"""
import logging
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from . import config
from .pipeline import FaceDetection

logger = logging.getLogger(__name__)


def load_face_model() -> FaceAnalysis:
    """
    Load InsightFace buffalo_l model pack.
    Called once at worker startup, 2 seconds after YOLO loads (staggered to prevent
    simultaneous memory spike on 8 GB RAM host).
    Model is baked into Docker image at build time — no download occurs here.
    """
    logger.info("Loading InsightFace buffalo_l (SCRFD + ArcFace R100)")
    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    # ctx_id=0 for CPU; det_size=(640,640) for full-resolution face detection
    face_app.prepare(ctx_id=0, det_size=(640, 640))
    logger.info("InsightFace buffalo_l loaded successfully")
    return face_app


def analyze_frame(
    frame_path: Path,
    face_app: FaceAnalysis,
) -> list[dict]:
    """
    Run InsightFace SCRFD + ArcFace on a single frame (full frame, not crop).
    Returns a list of raw face dicts — each has:
        bbox: [x1, y1, x2, y2]
        det_score: float
        normed_embedding: list[float] (512-dim, L2-normalized)

    Caller (run_insightface in pipeline.py) is responsible for pgvector matching.
    """
    frame_bgr = cv2.imread(str(frame_path))
    if frame_bgr is None:
        logger.warning("Could not read frame image: %s", frame_path)
        return []

    try:
        faces = face_app.get(frame_bgr)
    except Exception as exc:
        logger.error("InsightFace inference failed on %s: %s", frame_path.name, exc)
        return []

    results = []
    for face in faces:
        # CRITICAL: use face.normed_embedding, not face.embedding
        # normed_embedding is L2-normalized (unit vector) — correct for cosine similarity
        # face.embedding is raw (unnormalized) — DO NOT use for DB storage
        normed_emb = face.normed_embedding
        if normed_emb is None:
            logger.debug("Face has no normed_embedding — skipped (det_score=%.3f)", face.det_score)
            continue

        bbox = face.bbox  # [x1, y1, x2, y2] as floats
        results.append({
            "bbox_x1": int(bbox[0]),
            "bbox_y1": int(bbox[1]),
            "bbox_x2": int(bbox[2]),
            "bbox_y2": int(bbox[3]),
            "det_score": float(face.det_score),
            "normed_embedding": normed_emb.tolist(),   # convert numpy → list for pgvector
        })

    return results


async def match_face_embedding(
    normed_embedding: list[float],
    pool,
) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Search person_embeddings table via pgvector HNSW cosine similarity.
    Returns (matched_person_id, similarity, match_tier).

    Two-tier threshold:
        similarity >= FACE_MATCH_HIGH_THRESHOLD → ('confident', person_id, sim)
        FACE_MATCH_LOW_THRESHOLD <= sim < HIGH  → ('probable', person_id, sim)
        sim < FACE_MATCH_LOW_THRESHOLD          → (None, None, None) — genuine unknown

    Uses the HNSW index (m=32, ef_construction=128) with ef_search=64 set at DB level.
    Searches ALL embeddings for the best match, then takes the max similarity per person
    (a person may have multiple enrollment images).

    pgvector cosine distance operator (<=>): distance = 1 - cosine_similarity
    So similarity = 1 - distance.
    """
    high = config.FACE_MATCH_HIGH_THRESHOLD   # 0.65
    low = config.FACE_MATCH_LOW_THRESHOLD     # 0.50

    async with pool.acquire() as conn:
        # Best match: lowest cosine distance = highest cosine similarity
        # LIMIT 1 leverages the HNSW index efficiently
        row = await conn.fetchrow(
            """
            SELECT
                pe.person_id::text AS person_id,
                1.0 - (pe.normed_embedding <=> $1::vector) AS similarity
            FROM person_embeddings pe
            ORDER BY pe.normed_embedding <=> $1::vector
            LIMIT 1
            """,
            normed_embedding,
        )

    if row is None:
        # No persons enrolled yet — store as unknown
        return None, None, None

    similarity = float(row["similarity"])
    person_id = row["person_id"]

    if similarity >= high:
        return person_id, similarity, "confident"
    elif similarity >= low:
        return person_id, similarity, "probable"
    else:
        # Below low threshold — genuine unknown, enters HDBSCAN pool
        return None, similarity, None
```

**Notes on the pgvector query:**
- `$1::vector` casts the Python list to pgvector's `vector` type
- `<=>` is cosine distance (not inner product `<#>` or L2 `<->`)
- `ORDER BY <=> LIMIT 1` uses the HNSW index (m=32, ef_construction=128); ef_search=64 is set at the postgres service level via `hnsw.ef_search=64` command arg in docker-compose.yml
- `1.0 - distance` converts cosine distance to cosine similarity
- Even when similarity is below the low threshold, we still return the similarity value for audit logging (stored in `match_similarity` column even when `matched_person_id` is NULL)
</action>
<acceptance_criteria>
- `services/ingestion-worker/app/faces.py` exists
- `grep "load_face_model" services/ingestion-worker/app/faces.py` returns function definition
- `grep "normed_embedding" services/ingestion-worker/app/faces.py` returns at least 3 matches (variable names enforce correct field)
- `grep "face.embedding" services/ingestion-worker/app/faces.py` does NOT return any match (raw embedding forbidden)
- `grep "match_face_embedding" services/ingestion-worker/app/faces.py` returns async function definition
- `grep "normed_embedding <=> " services/ingestion-worker/app/faces.py` returns match (pgvector cosine distance query)
- `grep "FACE_MATCH_HIGH_THRESHOLD" services/ingestion-worker/app/faces.py` returns match using `config.FACE_MATCH_HIGH_THRESHOLD`
- `grep "FACE_MATCH_LOW_THRESHOLD" services/ingestion-worker/app/faces.py` returns match using `config.FACE_MATCH_LOW_THRESHOLD`
- `grep "CPUExecutionProvider" services/ingestion-worker/app/faces.py` returns match (CPU-only ONNX runtime)
- `grep "'confident'" services/ingestion-worker/app/faces.py` and `grep "'probable'" services/ingestion-worker/app/faces.py` both return matches (tier labels as string literals)
</acceptance_criteria>
</task>

<task id="04.2">
<title>Wire InsightFace into pipeline.py and main.py — replace stubs with real implementation</title>
<read_first>
- services/ingestion-worker/app/pipeline.py (current stub run_insightface() and process_video() — has_person gate already in place from Plan 02)
- services/ingestion-worker/app/main.py (current lifespan — asyncio.sleep(2) already in place from Plan 02; face_app = None stub)
- services/ingestion-worker/app/faces.py (just created: load_face_model, analyze_frame, match_face_embedding)
- .planning/STATE.md (YOLO loaded first; InsightFace loaded 2 seconds after — staggered to avoid memory spike)
- .planning/research/PITFALLS.md §FACE-05 (YOLO person detections and InsightFace face detections stored independently — different tables)
</read_first>
<action>
**Update `services/ingestion-worker/app/pipeline.py`** — replace the stub `run_insightface()` with a real async implementation:

Find the stub:
```python
async def run_insightface(
    frame_bgr_path: Path,
    face_app: Any,
    pool,
) -> list[FaceDetection]:
    """
    Stub. Plan 04 replaces this with real InsightFace inference + pgvector match.
    Returns list of FaceDetection for a single frame.
    """
    return []
```

Replace entirely with:
```python
async def run_insightface(
    frame_bgr_path: Path,
    face_app: Any,
    pool,
) -> list[FaceDetection]:
    """
    Run InsightFace buffalo_l on a single frame, then match each face against
    person_embeddings via pgvector HNSW cosine search.

    Returns one FaceDetection per detected face in the frame.

    CRITICAL DESIGN POINTS:
    - Called ONLY on frames where YOLO detected 'person' (enforced in process_video)
    - Runs AFTER all YOLO batch inference is complete (sequential, never parallel)
    - Uses face.normed_embedding (NOT face.embedding) — L2-normalized 512-dim vector
    - Stores YOLO person detections and face detections in SEPARATE tables (FACE-05)
    - Unmatched faces (similarity < LOW_THRESHOLD or no persons enrolled):
        matched_person_id = NULL, match_tier = NULL → enters HDBSCAN pool (Phase 3)
    """
    if face_app is None:
        logger.warning("InsightFace not loaded — returning empty face detections")
        return []

    from .faces import analyze_frame, match_face_embedding

    # Step 1: Detect faces and compute ArcFace embeddings (full frame, not YOLO crop)
    raw_faces = analyze_frame(frame_bgr_path, face_app)

    if not raw_faces:
        return []

    # Step 2: Match each face against enrolled persons via pgvector HNSW
    face_detections: list[FaceDetection] = []
    for raw in raw_faces:
        normed_emb = raw["normed_embedding"]

        matched_person_id, similarity, match_tier = await match_face_embedding(
            normed_emb, pool
        )

        face_detections.append(
            FaceDetection(
                bbox_x1=raw["bbox_x1"],
                bbox_y1=raw["bbox_y1"],
                bbox_x2=raw["bbox_x2"],
                bbox_y2=raw["bbox_y2"],
                det_score=raw["det_score"],
                normed_embedding=normed_emb,
                matched_person_id=matched_person_id,
                match_similarity=similarity,
                match_tier=match_tier,
            )
        )

    # Log tier breakdown for observability
    confident = sum(1 for f in face_detections if f.match_tier == "confident")
    probable = sum(1 for f in face_detections if f.match_tier == "probable")
    unknown = sum(1 for f in face_detections if f.match_tier is None)
    logger.debug(
        "Frame %s: %d faces — confident=%d probable=%d unknown=%d",
        frame_bgr_path.name,
        len(face_detections),
        confident,
        probable,
        unknown,
    )

    return face_detections
```

**Update `services/ingestion-worker/app/main.py`** — replace the InsightFace stub in the lifespan:

Find:
```python
    logger.info("Loading InsightFace buffalo_l")
    application.state.face_app = None      # Plan 04 replaces with FaceAnalysis(...)
    logger.info("InsightFace model loaded (stub)")
```

Replace with:
```python
    logger.info("Loading InsightFace buffalo_l (2s after YOLO to avoid RSS spike)")
    from .faces import load_face_model
    application.state.face_app = load_face_model()
    logger.info("InsightFace buffalo_l ready")
```

**Verify the face detection logging is end-to-end**: After process_video() in pipeline.py completes, the summary log line already includes `faces=%d`. Confirm it reports the correct count.

**Create a utility to verify normed_embedding normalization** — add this sanity check inside `analyze_frame()` in `faces.py`, right after `normed_emb = face.normed_embedding`:
```python
        # Sanity check: normed_embedding should be unit vector (L2 norm ≈ 1.0)
        # If this fires, something is wrong with the InsightFace version or usage
        norm = float(np.linalg.norm(normed_emb))
        if abs(norm - 1.0) > 0.01:
            logger.warning(
                "normed_embedding L2 norm=%.4f (expected ~1.0) — "
                "check InsightFace version; do NOT use face.embedding instead",
                norm,
            )
```

**Validate FACE-05 (independent storage)**: Confirm in `process_video()` that YOLO detections and face detections are written to SEPARATE tables.
The existing code already does this:
- `_write_detections(pool, frame_id, yolo_detections)` → writes to `detections` table
- `_write_face_detections(pool, frame_id, face_detections)` → writes to `face_detections` table

These are different tables; a frame can have YOLO person detections without face detections (face not visible) and vice versa. Add a code comment in `process_video()` after the face write to make this explicit:

After `result.faces_written += len(face_detections)`, add:
```python
            # NOTE (FACE-05): YOLO detections and InsightFace face detections are written
            # to separate tables (detections vs face_detections). A 'person' YOLO detection
            # means "a person-shaped object exists" — back turned, far away, no face visible.
            # A face_detection means "a face was detected and embedded". Both are stored
            # independently. The face pipeline runs only when has_person=True, but may
            # find 0 faces even when YOLO found a 'person' (face not visible to camera).
```
</action>
<acceptance_criteria>
- `grep "analyze_frame" services/ingestion-worker/app/pipeline.py` returns a match (real call, not stub)
- `grep "match_face_embedding" services/ingestion-worker/app/pipeline.py` returns a match
- `grep "face_app is None" services/ingestion-worker/app/pipeline.py` returns match (null guard for graceful handling)
- `grep "load_face_model" services/ingestion-worker/app/main.py` returns a match (real load in lifespan)
- `grep "application.state.face_app = None" services/ingestion-worker/app/main.py` does NOT return a match (stub removed)
- `grep "FACE-05" services/ingestion-worker/app/pipeline.py` returns the comment about independent storage
- `grep "normed_embedding.*L2 norm" services/ingestion-worker/app/faces.py` returns sanity check log line
- After `docker compose restart ingestion-worker`, logs show "InsightFace buffalo_l ready" appearing ~2 seconds after "YOLO model ready"
- After a full ingest of a video containing faces:
  - `SELECT COUNT(*) FROM face_detections;` returns > 0
  - `SELECT DISTINCT match_tier FROM face_detections;` shows NULL (unknown faces — no persons enrolled yet)
  - `SELECT LENGTH(normed_embedding::text) FROM face_detections LIMIT 1;` returns a large number (confirms 512-dim vector stored, not empty)
- `grep "separate tables" services/ingestion-worker/app/pipeline.py` OR grep "FACE-05" returns the independent storage comment
</acceptance_criteria>
</task>

---

## Verification

- [ ] `docker compose build ingestion-worker` succeeds after faces.py is added
- [ ] `docker compose restart ingestion-worker` shows in logs: "YOLO model ready", then ~2 seconds later "InsightFace buffalo_l ready"
- [ ] `docker compose logs ingestion-worker 2>&1 | grep -i "insightface"` shows "buffalo_l" in the loading log
- [ ] Ingest a video with visible faces (even if no persons are enrolled yet):
  - `SELECT COUNT(*) FROM face_detections;` returns > 0 rows
  - `SELECT COUNT(*) FROM detections WHERE class_name = 'person';` returns > 0 rows (separate tables, FACE-05)
  - `SELECT matched_person_id, match_tier FROM face_detections LIMIT 5;` shows all NULLs (no persons enrolled, so no matches)
- [ ] Enroll a test person manually (INSERT into known_persons + person_embeddings with a known embedding vector), then re-ingest the video with `?force=true`:
  - `SELECT match_tier, COUNT(*) FROM face_detections GROUP BY match_tier;` shows 'confident', 'probable', or NULL tiers
- [ ] `grep "face.embedding" services/ingestion-worker/app/faces.py` returns NO match (raw embedding never accessed)
- [ ] `grep "normed_embedding" services/ingestion-worker/app/faces.py` returns >= 3 matches

## must_haves

- InsightFace loads in `lifespan` exactly 2 seconds after YOLO (the `asyncio.sleep(2)` in `main.py` is the stagger mechanism)
- `faces.py` uses `face.normed_embedding` exclusively — `face.embedding` is never accessed anywhere in the codebase
- `match_face_embedding()` uses pgvector cosine distance operator `<=>` against `person_embeddings.normed_embedding` column
- Two-tier threshold: ≥0.65 → confident, 0.50–0.64 → probable, <0.50 → NULL/unknown
- Unmatched faces stored with `matched_person_id=NULL` and `match_tier=NULL` (Phase 3 HDBSCAN clustering picks these up)
- YOLO detections and face detections written to separate tables (`detections` vs `face_detections`) — FACE-05
- The L2 norm sanity check in `analyze_frame()` warns if `normed_embedding` is not a unit vector

## threat_model

### Threats

| Threat | Category | Mitigation |
|--------|----------|------------|
| [HIGH] Using `face.embedding` instead of `face.normed_embedding` silently produces wrong similarity scores | Information Disclosure / Integrity | `faces.py` uses only `face.normed_embedding`; L2 norm sanity check (≈1.0) logs a warning if something is wrong; `grep "face.embedding"` in CI would catch regression |
| [HIGH] Face similarity threshold too low causes false person matches in Telegram digest | Information Disclosure | Two-tier threshold (0.65 confident / 0.50 probable) with the lower tier excluded from digest; thresholds stored in config env vars so they can be tuned without code change |
| [MEDIUM] pgvector query returns a match when person_embeddings table is empty | Integrity | `match_face_embedding()` handles `row is None` (no rows = no enrolled persons) and returns `(None, None, None)` — face stored as unknown, not matched |
| [MEDIUM] InsightFace runs on frames without faces (wasted CPU on 8 GB host) | Availability | `run_insightface()` is gated by `has_person` in `process_video()` — only called when YOLO detected 'person'; analyze_frame returns early if no faces detected |
| [LOW] ArcFace embedding of a known person stored in pgvector with wrong dimensionality | Integrity | Schema enforces `vector(512)` constraint — pgvector rejects inserts with wrong dimension at the DB level |

---

<output>
After all tasks complete, create `.planning/phases/01-foundation/04-SUMMARY.md` with:
- InsightFace model loaded at startup with 2s delay (confirmed via logs: yes/no)
- face_detections table has rows after a test ingest (count)
- Two-tier threshold verified (match_tier values observed)
- FACE-05 independent storage confirmed (detections and face_detections both have rows)
- L2 norm sanity check observed in logs (yes/no)
- Any deviations from the plan
</output>
