---
plan: "03 — YOLO Object Detection"
phase: 1
wave: 3
depends_on:
  - "02"
files_modified:
  - services/ingestion-worker/app/detect.py
  - services/ingestion-worker/app/pipeline.py
  - services/ingestion-worker/app/main.py
autonomous: true
requirements:
  - DETECT-01
  - DETECT-02
  - DETECT-03
  - DETECT-04

must_haves:
  truths:
    - "YOLOv8n is loaded exactly once at worker startup inside the `lifespan` event — never per-frame or per-request"
    - "`YOLO_CLASSES` env var controls which COCO classes are detected; changing it and restarting changes output"
    - "Default COCO filter includes all 12 classes: person, bicycle, car, motorcycle, bus, truck, cat, dog, horse, sheep, cow, bird"
    - "YOLO runs in batches of `YOLO_BATCH_SIZE` (default 8) frames — never one frame at a time"
    - "After ingest, `detections` table rows exist for each frame with detected objects"
    - "YOLO detections are written with class_name, confidence, and bounding box"
  artifacts:
    - path: "services/ingestion-worker/app/detect.py"
      provides: "YOLO model wrapper with class filtering and batch inference"
      contains: "run_yolo_batch"
    - path: "services/ingestion-worker/app/pipeline.py"
      provides: "Updated pipeline calling real YOLO (no longer a stub)"
      contains: "run_yolo"
    - path: "services/ingestion-worker/app/main.py"
      provides: "Updated lifespan loading real YOLO model"
      contains: "YOLO("
  key_links:
    - from: "services/ingestion-worker/app/main.py lifespan"
      to: "services/ingestion-worker/app/detect.py load_yolo_model()"
      via: "app.state.yolo assignment at startup"
      pattern: "load_yolo_model"
    - from: "services/ingestion-worker/app/pipeline.py run_yolo()"
      to: "services/ingestion-worker/app/detect.py run_yolo_batch()"
      via: "direct function call"
      pattern: "run_yolo_batch"
    - from: "services/ingestion-worker/app/pipeline.py"
      to: "detections table"
      via: "_write_detections() in pipeline.py"
      pattern: "INSERT INTO detections"
---

# Plan 03: YOLO Object Detection

## Goal

Replace the `run_yolo()` stub in `pipeline.py` with real YOLOv8n batch inference. Implement `detect.py` with class filtering driven by `YOLO_CLASSES` env var. Update `main.py` to load the real YOLO model at startup. YOLO and InsightFace must always run sequentially (never parallel).

---

## Tasks

<task id="03.1">
<title>Create detect.py — YOLO model wrapper with class filtering</title>
<read_first>
- services/ingestion-worker/app/config.py (YOLO_MODEL, YOLO_CONFIDENCE, YOLO_CLASSES, YOLO_BATCH_SIZE)
- services/ingestion-worker/app/pipeline.py (Detection dataclass — must match exactly)
- requirements.md §6.1 (YOLO usage pattern: classes=ALLOWED_CLASS_IDS, imgsz=640, conf=0.35)
- .planning/research/ARCHITECTURE.md §Processing Pipeline §YOLO OBJECT DETECTION (batch 8–16 frames)
- .planning/research/SUMMARY.md §Docker Day 1 Checklist (DETECT-03: sequential not parallel)
</read_first>
<action>
Create `services/ingestion-worker/app/detect.py`:

```python
"""
YOLO object detection wrapper.

Key constraints (do not violate):
- Model is loaded ONCE at startup (load_yolo_model). Never re-loaded per frame.
- Inference runs in BATCHES of YOLO_BATCH_SIZE frames (default 8).
- Only classes in YOLO_CLASSES env var are returned. Others are filtered out.
- YOLO and InsightFace are always called SEQUENTIALLY — never in parallel.
"""
import logging
from pathlib import Path
from typing import Any

from ultralytics import YOLO

from . import config
from .pipeline import Detection

logger = logging.getLogger(__name__)

# ── COCO class name → class ID mapping ───────────────────────────────────────
# Source: https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml
_COCO_NAME_TO_ID: dict[str, int] = {
    "person": 0, "bicycle": 1, "car": 2, "motorcycle": 3, "airplane": 4,
    "bus": 5, "train": 6, "truck": 7, "boat": 8, "traffic light": 9,
    "fire hydrant": 10, "stop sign": 11, "parking meter": 12, "bench": 13,
    "bird": 14, "cat": 15, "dog": 16, "horse": 17, "sheep": 18, "cow": 19,
    "elephant": 20, "bear": 21, "zebra": 22, "giraffe": 23, "backpack": 24,
    "umbrella": 25, "handbag": 26, "tie": 27, "suitcase": 28, "frisbee": 29,
    "skis": 30, "snowboard": 31, "sports ball": 32, "kite": 33,
    "baseball bat": 34, "baseball glove": 35, "skateboard": 36,
    "surfboard": 37, "tennis racket": 38, "bottle": 39, "wine glass": 40,
    "cup": 41, "fork": 42, "knife": 43, "spoon": 44, "bowl": 45,
    "banana": 46, "apple": 47, "sandwich": 48, "orange": 49, "broccoli": 50,
    "carrot": 51, "hot dog": 52, "pizza": 53, "donut": 54, "cake": 55,
    "chair": 56, "couch": 57, "potted plant": 58, "bed": 59,
    "dining table": 60, "toilet": 61, "tv": 62, "laptop": 63, "mouse": 64,
    "remote": 65, "keyboard": 66, "cell phone": 67, "microwave": 68,
    "oven": 69, "toaster": 70, "sink": 71, "refrigerator": 72, "book": 73,
    "clock": 74, "vase": 75, "scissors": 76, "teddy bear": 77,
    "hair drier": 78, "toothbrush": 79,
}


def _resolve_class_ids(class_names: list[str]) -> list[int]:
    """
    Convert YOLO_CLASSES name list to COCO class IDs.
    Unknown names are logged and skipped (not fatal — flexible config).
    """
    ids = []
    for name in class_names:
        cid = _COCO_NAME_TO_ID.get(name.lower().strip())
        if cid is not None:
            ids.append(cid)
        else:
            logger.warning("YOLO_CLASSES: unknown class name '%s' — skipped", name)
    logger.info("YOLO active class IDs: %s (from %s)", ids, class_names)
    return ids


def load_yolo_model() -> YOLO:
    """
    Load the YOLO model from the baked image cache.
    Called once at worker startup (FastAPI lifespan). Never call per-frame.
    """
    logger.info("Loading YOLO model: %s", config.YOLO_MODEL)
    model = YOLO(config.YOLO_MODEL)
    logger.info("YOLO model loaded: %s", config.YOLO_MODEL)
    return model


def run_yolo_batch(
    frame_paths: list[Path],
    model: Any,
    allowed_class_ids: list[int],
) -> list[list[Detection]]:
    """
    Run YOLO inference on a batch of frames.
    Returns one list[Detection] per frame (same order as frame_paths).
    Only detections for allowed_class_ids are returned.

    Args:
        frame_paths: List of local JPEG paths for this batch (len 1–YOLO_BATCH_SIZE)
        model: Loaded YOLO model (from load_yolo_model())
        allowed_class_ids: COCO class IDs to keep (from _resolve_class_ids())

    Returns:
        list of lists — outer list indexed by frame, inner list is detections for that frame.
    """
    if not frame_paths:
        return []

    # Run batch inference. YOLO accepts a list of paths.
    results = model(
        [str(p) for p in frame_paths],
        imgsz=640,
        conf=config.YOLO_CONFIDENCE,
        classes=allowed_class_ids,
        verbose=False,   # suppress per-batch console spam
    )

    per_frame_detections: list[list[Detection]] = []

    for result in results:
        frame_detections: list[Detection] = []
        if result.boxes is None:
            per_frame_detections.append(frame_detections)
            continue

        boxes = result.boxes
        for box_idx in range(len(boxes)):
            cls_id = int(boxes.cls[box_idx].item())
            # Map COCO ID back to name using YOLO's own names dict
            class_name = result.names.get(cls_id, str(cls_id))
            conf = float(boxes.conf[box_idx].item())
            xyxy = boxes.xyxy[box_idx].cpu().numpy()
            x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])

            frame_detections.append(
                Detection(
                    class_name=class_name,
                    confidence=conf,
                    bbox_x1=x1,
                    bbox_y1=y1,
                    bbox_x2=x2,
                    bbox_y2=y2,
                )
            )

        per_frame_detections.append(frame_detections)

    return per_frame_detections
```
</action>
<acceptance_criteria>
- `services/ingestion-worker/app/detect.py` exists
- `grep "load_yolo_model" services/ingestion-worker/app/detect.py` returns function definition
- `grep "run_yolo_batch" services/ingestion-worker/app/detect.py` returns function definition
- `grep "_resolve_class_ids" services/ingestion-worker/app/detect.py` returns function (COCO name→ID mapping)
- `grep "_COCO_NAME_TO_ID" services/ingestion-worker/app/detect.py` returns dict with at least `"person": 0`
- `grep "verbose=False" services/ingestion-worker/app/detect.py` returns match (suppress YOLO console spam)
- `grep "allowed_class_ids" services/ingestion-worker/app/detect.py` returns match in function signature and model() call
- The 12 default classes are all present in `_COCO_NAME_TO_ID`: person, bicycle, car, motorcycle, bus, truck, cat, dog, horse, sheep, cow, bird
</acceptance_criteria>
</task>

<task id="03.2">
<title>Wire YOLO into pipeline.py and main.py — replace stubs with real implementation</title>
<read_first>
- services/ingestion-worker/app/pipeline.py (current stub run_yolo() function and process_video() loop)
- services/ingestion-worker/app/main.py (current lifespan — app.state.yolo = None stub)
- services/ingestion-worker/app/detect.py (just created: load_yolo_model, run_yolo_batch, _resolve_class_ids)
- .planning/research/ARCHITECTURE.md §Processing Pipeline §Frame batching strategy (batch 8–16, not one at a time)
- .planning/STATE.md (YOLO and InsightFace load sequentially at startup; 2-second delay between them)
</read_first>
<action>
**Update `services/ingestion-worker/app/pipeline.py`** — replace the stub `run_yolo()` function with a real implementation that calls `detect.py`:

Find the stub function:
```python
def run_yolo(
    frame_paths: list[Path],
    yolo_model: Any,
) -> list[list[Detection]]:
    """
    Stub. Plan 03 replaces this with real YOLOv8 batch inference.
    Returns one list of Detection per frame (same order as frame_paths).
    """
    return [[] for _ in frame_paths]
```

Replace it entirely with:
```python
def run_yolo(
    frame_paths: list[Path],
    yolo_model: Any,
) -> list[list[Detection]]:
    """
    Run YOLOv8 batch inference on a list of frame paths.
    Each call processes up to YOLO_BATCH_SIZE frames.
    Returns one list[Detection] per frame (same order as frame_paths).
    CRITICAL: Never called in parallel with run_insightface — sequential only.
    """
    if yolo_model is None:
        logger.warning("YOLO model not loaded — returning empty detections")
        return [[] for _ in frame_paths]

    from .detect import run_yolo_batch, _resolve_class_ids
    allowed_ids = _resolve_class_ids(config.YOLO_CLASSES)
    return run_yolo_batch(frame_paths, yolo_model, allowed_ids)
```

Also add to the top of `pipeline.py` imports (after existing imports):
```python
from . import config  # already present — verify it's there
```

**Update `services/ingestion-worker/app/main.py`** — replace the YOLO stub loading in the `lifespan` function:

Find:
```python
    logger.info("Loading YOLO model: %s", config.YOLO_MODEL)
    application.state.yolo = None          # Plan 03 replaces with YOLO("yolov8n.pt")
    logger.info("YOLO model loaded (stub)")
```

Replace with:
```python
    logger.info("Loading YOLO model: %s", config.YOLO_MODEL)
    from .detect import load_yolo_model
    application.state.yolo = load_yolo_model()
    logger.info("YOLO model ready")
```

**Verify the YOLO_CLASSES env var wiring** — add a startup log in `main.py` after YOLO loads to confirm the active class list:

Find (or add after YOLO loads):
```python
    from .detect import _resolve_class_ids
    active_ids = _resolve_class_ids(config.YOLO_CLASSES)
    logger.info("YOLO active classes: %s → IDs: %s", config.YOLO_CLASSES, active_ids)
```

**Also update `process_video()` in pipeline.py** — the batch loop already exists from Plan 02, but add a log line per batch for observability:

In the batch loop, after `all_yolo_results.extend(batch_results)`, add:
```python
            logger.debug(
                "[%s] YOLO batch %d/%d: %d detections",
                video_id[:8],
                batch_start // config.YOLO_BATCH_SIZE + 1,
                (len(frame_paths) + config.YOLO_BATCH_SIZE - 1) // config.YOLO_BATCH_SIZE,
                sum(len(r) for r in batch_results),
            )
```
</action>
<acceptance_criteria>
- `grep "run_yolo_batch" services/ingestion-worker/app/pipeline.py` returns a match (stub replaced with real call)
- `grep "yolo_model is None" services/ingestion-worker/app/pipeline.py` returns match (graceful null guard)
- `grep "load_yolo_model" services/ingestion-worker/app/main.py` returns a match (real load in lifespan)
- `grep "application.state.yolo = None" services/ingestion-worker/app/main.py` does NOT return a match (stub removed)
- `grep "active classes" services/ingestion-worker/app/main.py` returns match (startup log of YOLO_CLASSES)
- After `docker compose restart ingestion-worker`, `docker compose logs ingestion-worker` shows "YOLO model ready" and "YOLO active classes: ..."
- `curl -X POST http://localhost:8001/ingest -H "Content-Type: application/json" -d '{"minio_key":"videos/test.mp4"}'` returns 202; after processing completes, `docker compose exec postgres psql -U videosearch videosearch -c "SELECT COUNT(*) FROM detections;"` returns > 0 rows (requires a real video in MinIO)
- `docker compose exec postgres psql -U videosearch videosearch -c "SELECT DISTINCT class_name FROM detections;"` only shows classes from the 12-class default list
</acceptance_criteria>
</task>

---

## Verification

- [ ] `docker compose build ingestion-worker` succeeds after detect.py is added
- [ ] `docker compose restart ingestion-worker` logs show YOLO model loading with model name and class IDs
- [ ] Setting `YOLO_CLASSES=person,car` in `.env`, restarting, and ingesting a video results in only `person` and `car` rows in the `detections` table
- [ ] After processing a video with people visible, `SELECT class_name, COUNT(*) FROM detections GROUP BY class_name;` shows detections of expected classes
- [ ] YOLO batch size is configurable: `YOLO_BATCH_SIZE=16` in `.env` changes the batch size
- [ ] `grep "Never called in parallel" services/ingestion-worker/app/pipeline.py` confirms the sequential constraint comment is present

## must_haves

- YOLO model is loaded once at startup, stored in `app.state.yolo`, passed to `process_video()` — never loaded inside the request handler or frame loop
- `run_yolo_batch()` in `detect.py` accepts `allowed_class_ids` and passes it to `model(classes=...)` — YOLO_CLASSES env var controls output
- The 12 default COCO classes (person, bicycle, car, motorcycle, bus, truck, cat, dog, horse, sheep, cow, bird) are all in `_COCO_NAME_TO_ID`
- YOLO runs in batches (not one frame at a time); batch size is `config.YOLO_BATCH_SIZE`
- YOLO results are written to the `detections` table with class_name, confidence, bbox_x1/y1/x2/y2, frame_id FK
- YOLO runs sequentially before InsightFace (pipeline.py enforces this via ordering, not threading)

## threat_model

### Threats

| Threat | Category | Mitigation |
|--------|----------|------------|
| [MEDIUM] YOLO loading unknown class names from YOLO_CLASSES env var (misconfiguration) | Tampering | `_resolve_class_ids()` logs a warning for unknown names and skips them (does not crash); at worst, detection filter is wider than intended |
| [LOW] YOLO model file tampered with in Docker image | Tampering | Model is baked at build time (`FROM` layer is content-addressed by Docker); rebuilding the image re-downloads from Ultralytics CDN. For production: pin the model SHA in the Dockerfile. |
| [LOW] Batch processing holds large list of frame paths in memory | Denial of Service | `YOLO_BATCH_SIZE` (default 8) limits concurrent frame loading; on 8 GB host with 1280-px frames, 8 × ~0.8 MB = ~6 MB — negligible |

---

<output>
After all tasks complete, create `.planning/phases/01-foundation/03-SUMMARY.md` with:
- YOLO model loaded at startup (confirmed via logs: yes/no)
- YOLO_CLASSES env var verified to control detection output (yes/no)
- Sample detection counts from a test video
- Any deviations from the plan
</output>
