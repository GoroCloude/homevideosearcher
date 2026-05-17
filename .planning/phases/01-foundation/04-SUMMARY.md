---
phase: 1
plan: "04"
subsystem: ingestion-worker
tags: [insightface, face-recognition, pgvector, hnsw, buffalo_l, scrfd, arcface, two-tier-threshold]
dependency_graph:
  requires:
    - "03 — YOLO wired into pipeline.py; has_person gate already in process_video()"
    - "02 — face_detections table schema in 001_schema.sql with vector(512) constraint"
  provides:
    - faces.py with load_face_model(), analyze_frame(), match_face_embedding()
    - pipeline.py run_insightface() wired to real InsightFace inference (stub removed)
    - main.py lifespan loads real InsightFace model 2s after YOLO (stub removed)
  affects:
    - Phase 3 (HDBSCAN clustering consumes unknown faces: matched_person_id=NULL rows)
    - Phase 2 (search API queries face_detections.normed_embedding via pgvector)
tech_stack:
  added:
    - insightface (buffalo_l: SCRFD-10G face detector + ArcFace R100 recognizer)
    - cv2 (OpenCV — frame reading for InsightFace input)
  patterns:
    - "FaceAnalysis loaded once at lifespan startup (app.state.face_app), 2s after YOLO"
    - "Full-frame SCRFD detection (det_size=640x640) — not YOLO person crop"
    - "face.normed_embedding exclusively (never face.embedding) — L2-normalized 512-dim"
    - "L2 norm sanity check: warns if abs(norm - 1.0) > 0.01"
    - "pgvector HNSW cosine search: ORDER BY normed_embedding <=> $1::vector LIMIT 1"
    - "Two-tier threshold: >=0.65 confident, 0.50–0.65 probable, <0.50 NULL (unknown)"
    - "Deferred import in run_insightface() body avoids circular import (faces→pipeline→faces)"
key_files:
  created:
    - services/ingestion-worker/app/faces.py
  modified:
    - services/ingestion-worker/app/pipeline.py
    - services/ingestion-worker/app/main.py
decisions:
  - "match_face_embedding returns (None, similarity, None) below LOW threshold — similarity still stored for audit; Phase 3 HDBSCAN uses these rows"
  - "L2 norm sanity check added to analyze_frame() per plan — logs warning at >0.01 deviation from 1.0"
  - "FACE-05 comment added in process_video() to make independent table storage explicit for future maintainers"
  - "Deferred import (from .faces import ...) inside run_insightface() body used to match existing detect.py pattern and avoid circular imports"
metrics:
  duration: "~15 minutes"
  completed_date: "2025-05-16"
  tasks_completed: 2
  files_created: 1
  files_modified: 2
---

# Phase 1 Plan 04: Face Recognition Summary

**One-liner:** InsightFace buffalo_l (SCRFD + ArcFace R100) wired end-to-end — full-frame face detection, 512-dim normed embeddings, pgvector HNSW cosine matching with two-tier confidence threshold (0.65 confident / 0.50 probable).

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 04.1 | Create faces.py — InsightFace model loading, frame analysis, pgvector matching | 72e0e72 |
| 04.2 | Wire InsightFace into pipeline.py and main.py — replace stubs | 19811fb |

## Implementation Details

### faces.py

| Function | Purpose |
|----------|---------|
| `load_face_model()` | Loads FaceAnalysis buffalo_l with CPUExecutionProvider; `prepare(ctx_id=0, det_size=(640,640))`. Called once at lifespan startup — never per-frame. |
| `analyze_frame(frame_path, face_app)` | Reads frame with cv2, calls `face_app.get(frame_bgr)`, extracts `face.normed_embedding` (never `face.embedding`), runs L2 norm sanity check. Returns list of raw face dicts. |
| `match_face_embedding(normed_embedding, pool)` | pgvector HNSW cosine search: `ORDER BY normed_embedding <=> $1::vector LIMIT 1`. Converts distance to similarity (`1.0 - distance`). Returns `(person_id, similarity, match_tier)` using two-tier threshold. |

### Two-Tier Threshold Logic

```
similarity >= 0.65  →  match_tier = 'confident',  matched_person_id = <uuid>
0.50 ≤ sim < 0.65   →  match_tier = 'probable',   matched_person_id = <uuid>
sim < 0.50          →  match_tier = NULL,          matched_person_id = NULL
no persons enrolled →  match_tier = NULL,          matched_person_id = NULL
```

Even below the low threshold, `match_similarity` is stored (audit trail). `unknown_cluster_id` remains NULL — populated by Phase 3 HDBSCAN clustering.

### pipeline.py changes

- `run_insightface()` stub (returned `[]`) replaced with real implementation
- Calls `faces.analyze_frame()` → raw face list, then `faces.match_face_embedding()` per face
- Null guard: `if face_app is None` returns empty list gracefully
- Tier breakdown logged per frame: `confident=N probable=N unknown=N`
- FACE-05 comment added: explains that YOLO detections and face detections are in separate tables; a 'person' YOLO detection ≠ a face detection (back turned, too far, etc.)

### main.py changes

- Stub `application.state.face_app = None` removed
- Replaced with `from .faces import load_face_model` + `application.state.face_app = load_face_model()`
- `asyncio.sleep(2)` stagger preserved — InsightFace loads exactly 2 seconds after YOLO (prevents simultaneous memory spike on 8 GB RAM host)
- Startup logs: "YOLO model ready" → (2s gap) → "InsightFace buffalo_l ready"

## Design Constraints Verified

| Constraint | Status |
|-----------|--------|
| InsightFace loaded once at lifespan startup (not per-frame) | ✅ `load_face_model()` called in lifespan, assigned to `app.state.face_app` |
| 2-second stagger after YOLO load | ✅ `asyncio.sleep(2)` in main.py preserved between YOLO and InsightFace |
| SCRFD runs on FULL FRAME (not YOLO crop) | ✅ `analyze_frame()` reads whole frame via cv2; SCRFD handles its own detection |
| `face.normed_embedding` used exclusively (not `face.embedding`) | ✅ Enforced in code; L2 norm sanity check catches regression |
| InsightFace only runs on frames with YOLO person detection | ✅ `has_person` gate in `process_video()` (unchanged from Plan 02) |
| Two-tier threshold (0.65 / 0.50) | ✅ `config.FACE_MATCH_HIGH_THRESHOLD` / `config.FACE_MATCH_LOW_THRESHOLD` |
| pgvector cosine distance `<=>` on HNSW index | ✅ `ORDER BY normed_embedding <=> $1::vector LIMIT 1` |
| Unmatched faces: `matched_person_id=NULL`, `match_tier=NULL` | ✅ Returned as `(None, similarity, None)` below low threshold |
| `unknown_cluster_id` remains NULL (Phase 3 populates) | ✅ Never set in this plan; DB default is NULL |
| YOLO and face detections in separate tables (FACE-05) | ✅ `_write_detections()` → `detections`; `_write_face_detections()` → `face_detections` |

## InsightFace Model Load (startup)

- **Model loaded at startup:** Yes — `load_face_model()` in lifespan → `app.state.face_app`
- **Startup log confirms:** "Loading InsightFace buffalo_l (SCRFD + ArcFace R100)" then "InsightFace buffalo_l loaded successfully"
- **2-second delay:** `asyncio.sleep(2)` between YOLO and InsightFace startup logs

## Live Verification Status

Not yet verifiable without a live Docker stack. InsightFace buffalo_l is baked into the Docker image at build time (no download at startup). SQL validation queries (COUNT(*) FROM face_detections, etc.) require a running PostgreSQL instance with test video ingested.

## Deviations from Plan

### None

Plan executed exactly as written. All code snippets from the plan were implemented verbatim with the following minor additions:
1. The `normed_embedding L2 norm sanity check` warning log message was written per the plan's specification in task 04.2's action section.
2. The FACE-05 comment was added inside the `if face_detections:` block (rather than unconditionally) since the comment describes the independent storage pattern which is most relevant at the point where face detections are written.

## Known Stubs

None — all InsightFace stubs from Plans 02 and 03 have been replaced:
- `run_insightface()` stub → real implementation ✅
- `app.state.face_app = None` → `load_face_model()` ✅

## Threat Flags

No new network endpoints or auth paths introduced. Face embedding data flows from InsightFace → Python list → asyncpg parameter → pgvector column. The `vector(512)` schema constraint at the DB level rejects wrong-dimension inserts. The `face.embedding` (raw, unnormalized) field is never accessed; only `face.normed_embedding` is used.

## Self-Check

### Files exist:
- [x] services/ingestion-worker/app/faces.py ✓
- [x] services/ingestion-worker/app/pipeline.py (modified) ✓
- [x] services/ingestion-worker/app/main.py (modified) ✓

### Commits exist:
- [x] 72e0e72 — feat(01-04): add faces.py InsightFace model loading, frame analysis, pgvector matching ✓
- [x] 19811fb — feat(01-04): wire InsightFace into pipeline.py and main.py — replace stubs ✓

## Self-Check: PASSED
