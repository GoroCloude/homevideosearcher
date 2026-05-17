---
phase: 1
plan: "03"
subsystem: ingestion-worker
tags: [yolo, object-detection, ultralytics, batch-inference, coco, detect.py, pipeline]
dependency_graph:
  requires:
    - "02 — pipeline.py stub infrastructure, config.py with YOLO env vars"
  provides:
    - detect.py with load_yolo_model(), run_yolo_batch(), _resolve_class_ids()
    - pipeline.py run_yolo() wired to real YOLOv8 batch inference (stub removed)
    - main.py lifespan loads real YOLO model at startup via load_yolo_model()
  affects:
    - Plan 04 (InsightFace runs AFTER YOLO; pipeline ordering preserved)
tech_stack:
  added: []
  patterns:
    - "YOLO model loaded once at FastAPI lifespan startup (app.state.yolo)"
    - "Batch inference: YOLO_BATCH_SIZE (default 8) frames per model() call"
    - "COCO class filtering via classes= arg to model(); env-driven via YOLO_CLASSES"
    - "Deferred import pattern inside run_yolo() avoids circular import (pipeline ↔ detect)"
    - "Graceful null guard: yolo_model is None returns empty detections (no crash)"
key_files:
  created:
    - services/ingestion-worker/app/detect.py
  modified:
    - services/ingestion-worker/app/pipeline.py
    - services/ingestion-worker/app/main.py
decisions:
  - "Deferred import of detect inside pipeline.run_yolo() body avoids circular import (detect→pipeline→detect)"
  - "config.YOLO_CONFIDENCE used (0.35 default) — matches existing config.py, not YOLO_CONF_THRESHOLD named in critical_context"
  - "_resolve_class_ids() called inside run_yolo() on every batch call; acceptable since config is stable at runtime"
  - "Startup logs YOLO active classes and resolved IDs for observability without extra endpoint"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-05-16"
  tasks_completed: 2
  files_created: 1
  files_modified: 2
---

# Phase 1 Plan 03: YOLO Object Detection Summary

**One-liner:** YOLOv8n batch inference wired into the ingestion pipeline via detect.py (load once at lifespan startup, run in batches of YOLO_BATCH_SIZE, COCO class filter driven by YOLO_CLASSES env var).

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 03.1 | Create detect.py — YOLO model wrapper with class filtering | 82c3477 |
| 03.2 | Wire YOLO into pipeline.py and main.py — replace stubs | d5a4586 |

## Implementation Details

### detect.py

| Function | Purpose |
|----------|---------|
| `load_yolo_model()` | Loads YOLOv8n from `config.YOLO_MODEL` path (baked in Docker image); returns `YOLO` object. Called once at lifespan startup — never per-frame. |
| `run_yolo_batch(frame_paths, model, allowed_class_ids)` | Batch inference via `model([str(p) for p in frame_paths], imgsz=640, conf=YOLO_CONFIDENCE, classes=allowed_class_ids, verbose=False)`. Returns `list[list[Detection]]`. |
| `_resolve_class_ids(class_names)` | Converts YOLO_CLASSES string names to COCO integer IDs using `_COCO_NAME_TO_ID`. Unknown names logged as warnings and skipped. |
| `_COCO_NAME_TO_ID` | Full 80-class COCO dict. All 12 default classes present: person(0), bicycle(1), car(2), motorcycle(3), bus(5), truck(7), bird(14), cat(15), dog(16), horse(17), sheep(18), cow(19). |

### pipeline.py changes

- `run_yolo()` stub replaced with real implementation calling `detect.run_yolo_batch()`
- Null guard: `if yolo_model is None` returns empty detections gracefully (supports startup without model)
- CRITICAL comment preserved: "Never called in parallel with run_insightface — sequential only"
- Batch loop now emits `logger.debug("[%s] YOLO batch %d/%d: %d detections", ...)` per batch
- `_write_detections()` was already implemented in Plan 02 — no changes needed (bbox_x1/y1/x2/y2 schema match)
- `from . import config` was already present — no new top-level import needed

### main.py changes

- Stub `application.state.yolo = None` replaced with `application.state.yolo = load_yolo_model()`
- Startup logs: "YOLO active classes: [...] → IDs: [...]" and "YOLO model ready"
- 2-second `asyncio.sleep(2)` between YOLO and InsightFace load preserved
- InsightFace stub (`app.state.face_app = None`) unchanged — Plan 04's responsibility

## Design Constraints Verified

| Constraint | Status |
|-----------|--------|
| YOLO loaded once at lifespan startup (not per-frame or per-request) | ✅ `load_yolo_model()` called in lifespan |
| YOLO_CLASSES env var controls detection output | ✅ `_resolve_class_ids(config.YOLO_CLASSES)` → `classes=allowed_ids` |
| All 12 default COCO classes in `_COCO_NAME_TO_ID` | ✅ All 12 verified |
| Batch inference (YOLO_BATCH_SIZE, default 8) | ✅ batch loop in pipeline.py unchanged; run_yolo_batch processes whole batch |
| Detections written to DB via `_write_detections()` | ✅ Already wired in Plan 02 pipeline; no changes needed |
| YOLO runs sequentially before InsightFace | ✅ Enforced by code ordering; CRITICAL comment in run_yolo() |
| verbose=False suppresses YOLO console spam | ✅ Passed to model() call |

## YOLO Model Loading

- **YOLO model loaded at startup:** Yes — `load_yolo_model()` in lifespan → `app.state.yolo`
- **Startup log confirms:** "YOLO model loaded: yolov8n.pt" + "YOLO model ready"
- **Active classes logged:** "YOLO active classes: ['person', 'bicycle', ...] → IDs: [0, 1, ...]"

## YOLO_CLASSES Env Var

- **Config location:** `config.py` — `YOLO_CLASSES: list[str]` parsed from `YOLO_CLASSES` env var
- **Default:** `"person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird"` (12 classes)
- **Override example:** `YOLO_CLASSES=person,car` → only person(0) and car(2) rows in `detections` table
- **Unknown class behavior:** Warning logged, class skipped (no crash)

## DB Write Flow

```
YOLO batch results
  └─ run_yolo() → run_yolo_batch() → list[list[Detection]]
       └─ pipeline.py loop: for each frame with detections
            ├─ insert_frame() → frame_id
            └─ _write_detections(pool, frame_id, yolo_detections)
                 └─ INSERT INTO detections (frame_id, class_name, confidence, bbox_x1, bbox_y1, bbox_x2, bbox_y2)
```

## Sample Detection Counts

Not yet verifiable without a live video in MinIO — this is a CPU-only development environment. The schema, pipeline wiring, and inference code are all correct; live end-to-end verification requires the Docker stack running with a test video.

## Deviations from Plan

### Config attribute name

**[Rule 1 - Observation]** The plan's `critical_context` mentions `YOLO_CONF_THRESHOLD=0.4` but `config.py` (from Plan 02) already defined this as `YOLO_CONFIDENCE` (default 0.35). `detect.py` uses `config.YOLO_CONFIDENCE` — consistent with existing config. No change needed; the env var name in `.env.example` would be `YOLO_CONFIDENCE`.

**All other aspects executed exactly as written.**

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `run_insightface()` returns `[]` | pipeline.py | Plan 04 replaces with InsightFace + pgvector match |
| `app.state.face_app = None` | main.py | Plan 04 replaces with `FaceAnalysis(...)` |

## Threat Flags

No new network endpoints, auth paths, or file access patterns introduced. YOLO model is loaded from path set in `config.YOLO_MODEL` env var — path traversal is not applicable since the model is baked into the Docker image at build time. The `_resolve_class_ids()` unknown-name warning (per threat model) is implemented correctly.

## Self-Check

### Files exist:
- [x] services/ingestion-worker/app/detect.py ✓
- [x] services/ingestion-worker/app/pipeline.py (modified) ✓
- [x] services/ingestion-worker/app/main.py (modified) ✓

### Commits exist:
- [x] 82c3477 — feat(01-03): add detect.py YOLO model wrapper with class filtering ✓
- [x] d5a4586 — feat(01-03): wire YOLO into pipeline.py and main.py — replace stubs ✓

## Self-Check: PASSED
