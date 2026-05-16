---
phase: 1
plan: "02"
subsystem: ingestion-worker
tags: [fastapi, asyncpg, minio, ffmpeg, pipeline, yolo-stub, insightface-stub, pgvector]
dependency_graph:
  requires:
    - "01 — docker-compose stack, PostgreSQL schema, Dockerfiles"
  provides:
    - config.py with typed env-var reading and two-tier face thresholds
    - db.py with asyncpg pool (min=2, max=10), pgvector codec, SQL helpers
    - storage.py with MinIO client, upload_frame, download_video, list_video_keys
    - frames.py with FFmpeg 1-fps + scene-change extraction and probe_video_metadata
    - pipeline.py with full state machine (pending→processing→done|failed), stub YOLO/InsightFace
    - main.py with lifespan startup, POST /ingest, POST /ingest/batch, GET /health
  affects:
    - Plan 03 (fills in run_yolo stub in pipeline.py)
    - Plan 04 (fills in run_insightface stub in pipeline.py)
tech_stack:
  added: []
  patterns:
    - "asyncpg pool min_size=2, max_size=10 with pgvector codec registered at startup"
    - "FastAPI lifespan for startup/shutdown resource management"
    - "Staggered model loading: YOLO first, 2s sleep, InsightFace (memory spike guard)"
    - "BackgroundTasks for async video processing without blocking HTTP response"
    - "Selective frame storage: only frames with detections uploaded to MinIO"
    - "InsightFace gated on YOLO person detection (FR-3 pitfall avoidance)"
    - "Crash recovery: reset_stale_processing_videos() resets processing→pending on startup"
    - "FFmpeg subprocess (list-form, no shell=True) for safe video frame extraction"
key_files:
  created:
    - services/ingestion-worker/app/config.py
    - services/ingestion-worker/app/db.py
    - services/ingestion-worker/app/storage.py
    - services/ingestion-worker/app/frames.py
    - services/ingestion-worker/app/pipeline.py
  modified:
    - services/ingestion-worker/app/main.py
decisions:
  - "config.py uses plain os.environ/os.getenv (not pydantic-settings) — no extra dependency needed"
  - "run_yolo() and run_insightface() are synchronous and async stubs respectively — Plans 03/04 replace in-place without changing call sites"
  - "SCENE_THRESHOLD set to 0.4 (plan spec used 0.3 in FFmpeg filter but 0.4 in code example — kept 0.4 per code block)"
  - "upload_frame() key format: frames/{video_id}/{ts_ms}.jpg — matches DB schema minio_key pattern"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-05-16"
  tasks_completed: 3
  files_created: 5
  files_modified: 1
---

# Phase 1 Plan 02: Ingestion Worker Summary

**One-liner:** FastAPI ingestion-worker with asyncpg pool, MinIO client, FFmpeg frame extraction, and full video processing pipeline (pending→processing→done|failed state machine) with stub YOLO/InsightFace hooks for Plans 03 and 04.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 02.1 | config.py, db.py, storage.py — foundation modules | 3e5bace |
| 02.2 | frames.py + main.py replacement — FFmpeg extraction + FastAPI lifespan | a041b58 |
| 02.3 | pipeline.py — end-to-end video processing orchestration | 83683ab |

## Modules Created

| Module | Purpose |
|--------|---------|
| `config.py` | All env var reading with typed defaults; FACE_MATCH_HIGH_THRESHOLD=0.65, FACE_MATCH_LOW_THRESHOLD=0.50 |
| `db.py` | asyncpg pool (min=2, max=10), pgvector codec registration, SQL helpers: get_or_create_video, update_video_status, update_video_metadata, insert_frame, reset_stale_processing_videos |
| `storage.py` | MinIO client wrapper: download_video, upload_frame (→ frames/{video_id}/{ts_ms}.jpg), list_video_keys |
| `frames.py` | FFmpeg 1-fps + scene-change extraction (two-pass), ExtractedFrame dataclass, probe_video_metadata |
| `pipeline.py` | Full pipeline: download → extract → YOLO batch → InsightFace per-frame → selective upload → DB write; stub run_yolo() + run_insightface() |
| `main.py` | FastAPI lifespan (DB pool, crash recovery, staggered model loading); GET /health, POST /ingest, POST /ingest/batch |

## Endpoint Status

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /health` | ✅ Returns `{"status":"ok","service":"ingestion-worker"}` | |
| `POST /ingest` | ✅ 202 + BackgroundTask; skips if done unless ?force=true | |
| `POST /ingest/batch` | ✅ Scans MinIO prefix, enqueues .mp4/.mov/.avi/.mkv | |

## Recovery Mechanism

**Verified: Yes** — `reset_stale_processing_videos()` is called in the lifespan startup handler before model loading. It updates any videos stuck in `status='processing'` back to `'pending'` and logs a warning with the count. This handles the crash-during-processing scenario.

## Critical Design Rules Verified

| Rule | Verified |
|------|---------|
| YOLO and InsightFace load ONCE at lifespan startup (stubs now) | ✅ |
| 2-second asyncio.sleep between YOLO and InsightFace load | ✅ |
| Only frames WITH detections uploaded to MinIO (has_any_detection gate) | ✅ |
| InsightFace gated on YOLO `has_person` flag | ✅ |
| YOLO and InsightFace run sequentially (never parallel) | ✅ documented in code |
| normed_embedding (not embedding) in all INSERT statements | ✅ |
| match_tier written in face_detections INSERT | ✅ |
| Crash recovery resets processing→pending on startup | ✅ |
| minio_key path extracted via split("/")[-1] (no path traversal) | ✅ |
| subprocess calls use list-form (no shell=True) | ✅ |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `run_yolo()` returns `[[] for _ in frame_paths]` | pipeline.py | ~63 | Plan 03 replaces with real YOLOv8 inference |
| `run_insightface()` returns `[]` | pipeline.py | ~74 | Plan 04 replaces with InsightFace + pgvector match |
| `app.state.yolo = None` | main.py | ~35 | Plan 03 replaces with `YOLO("yolov8n.pt")` |
| `app.state.face_app = None` | main.py | ~41 | Plan 04 replaces with `FaceAnalysis(...)` |

These stubs are intentional — the pipeline shell is complete; detection logic is the next phase.

## Self-Check

### Files exist:
- [x] services/ingestion-worker/app/config.py ✓
- [x] services/ingestion-worker/app/db.py ✓
- [x] services/ingestion-worker/app/storage.py ✓
- [x] services/ingestion-worker/app/frames.py ✓
- [x] services/ingestion-worker/app/pipeline.py ✓
- [x] services/ingestion-worker/app/main.py (replaced stub) ✓
- [x] services/ingestion-worker/app/__init__.py (pre-existing, empty) ✓

### Commits exist:
- [x] 3e5bace — feat(01-02): add config.py, db.py, storage.py ✓
- [x] a041b58 — feat(01-02): add frames.py and replace main.py ✓
- [x] 83683ab — feat(01-02): add pipeline.py ✓

## Self-Check: PASSED
