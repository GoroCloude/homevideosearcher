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
