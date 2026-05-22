---
phase: 06-video-detail-delete-api
plan: "01"
subsystem: api
tags: [fastapi, pydantic, minio, presigned-urls, video-detail]
dependency_graph:
  requires: [videos router (existing), generate_presigned_url, MINIO_BUCKET_FRAMES config]
  provides: [VideoDetail model, DetectionItem model, FaceItem model, GET /videos/{id}, GET /videos/{id}/detections, GET /videos/{id}/faces]
  affects: [Phase 7 VideoDetailPage React components]
tech_stack:
  added: []
  patterns: [presigned URL on-demand generation, window function for appearance_count, asyncpg fetchrow/fetch pattern]
key_files:
  modified:
    - services/api/app/videos.py
decisions:
  - Route GET /{video_id} placed before /{video_id}/stream so FastAPI resolves specific paths first — no routing conflict
  - appearance_count computed via SQL window function PARTITION BY COALESCE(matched_person_id, unknown_cluster_id) — avoids Python-side aggregation
  - NULL cluster_id_prefix guarded with `or 'unknown'` — handles face detections with neither person nor cluster assignment
metrics:
  duration: ~10m
  completed: 2025-05-21
  tasks: 3
  files_modified: 1
---

# Phase 6 Plan 01: Video Detail & Detection Read Endpoints Summary

**One-liner:** Three new GET endpoints (video detail + YOLO detections + face detections) with presigned MinIO thumbnail URLs and SQL window-function appearance counts, appended to existing videos router without touching any existing code.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | VideoDetail model + GET /videos/{id} | e4ec459 | services/api/app/videos.py |
| 2 | DetectionItem model + GET /videos/{id}/detections | 2b3724a | services/api/app/videos.py |
| 3 | FaceItem model + GET /videos/{id}/faces | 607bd25 | services/api/app/videos.py |

## What Was Built

### New Pydantic Models
- **`VideoDetail`** (12 fields): id, filename, minio_key, status, error_message, recorded_at, duration_sec, ingested_at, frame_count, detection_count, face_count, stream_url
- **`DetectionItem`** (7 fields): id, frame_id, ts_ms, thumbnail_url, label, confidence, bbox_json
- **`FaceItem`** (6 fields): id, frame_id, ts_ms, thumbnail_url, person_name, appearance_count

### New Endpoints
- `GET /videos/{video_id}` — aggregate metadata + presigned stream URL (1h TTL)
- `GET /videos/{video_id}/detections` — all YOLO detections ordered by ts_ms with presigned frame thumbnails
- `GET /videos/{video_id}/faces` — all face detections with resolved person names and window-function appearance counts

### Key Implementation Details
- `filename` derived as `minio_key.split("/")[-1]` — pure basename extraction
- `thumbnail_url` generated on-demand via `generate_presigned_url(config.MINIO_BUCKET_FRAMES, ...)` per row
- Face name resolution priority: `persons.name` → `unknown_clusters.label_name` → `"Unknown Cluster #<uuid8>"`
- NULL guard on `cluster_id_prefix`: `r['cluster_id_prefix'] or 'unknown'`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all endpoints return real DB data with live presigned URLs.

## Threat Flags

No new threat surface introduced. All endpoints inherit `require_token` from `videos_router` registration in `main.py`. Presigned URLs use HMAC+TTL (MinIO), expire in 1h.

## Self-Check: PASSED

- `services/api/app/videos.py` exists and parses cleanly (Python AST)
- 7 route decorators present (4 existing + 3 new)
- 3 new models: VideoDetail, DetectionItem, FaceItem
- 5 original models untouched
- MINIO_BUCKET_FRAMES referenced (4 occurrences)
- `cluster_id_prefix or 'unknown'` guard present
- Commits e4ec459, 2b3724a, 607bd25 exist in git log
