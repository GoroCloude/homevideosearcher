---
phase: 06-video-detail-delete-api
plan: "02"
subsystem: api
tags: [fastapi, asyncpg, minio, delete, cascade, hard-delete]
dependency_graph:
  requires: [videos router, get_minio_client (storage.py), MINIO_BUCKET_VIDEOS, MINIO_BUCKET_FRAMES, asyncpg conn.transaction()]
  provides: [DELETE /videos/{id} — hard delete with DB cascade + MinIO cleanup]
  affects: [Phase 7 VideoDetailPage (delete button), Phase 6 VideoListPage (removes deleted entry)]
tech_stack:
  added: [minio.deleteobjects.DeleteObject (minio-py bulk delete API)]
  patterns: [asyncpg conn.transaction() for atomic multi-table delete, best-effort MinIO cleanup after DB commit, remove_objects streaming iterator]
key_files:
  modified:
    - services/api/app/videos.py
decisions:
  - MinIO cleanup placed after DB transaction commit — DB deletion is authoritative; MinIO errors are logged but never raise
  - Frame minio_keys fetched before DB delete inside the same connection — avoids re-query after transaction
  - remove_objects used for bulk frame thumbnail deletion (streaming iterator); remove_object used for single video file
  - from minio.deleteobjects import DeleteObject placed inside the function — avoids top-level import side-effect at module load
  - require_token NOT added to videos.py — auth is inherited via router-level Depends(require_token) in main.py
metrics:
  duration: ~10m
  completed: 2025-05-21
  tasks: 1 (+ 1 pending human verify checkpoint)
  files_modified: 1
requirements:
  - DEL-03
  - DEL-05
---

# Phase 6 Plan 02: DELETE /videos/{id} Endpoint Summary

**One-liner:** Hard-delete endpoint that atomically removes all DB rows (face_detections → detections → frames → videos) in a single asyncpg transaction then best-effort removes the MinIO video file and frame thumbnails, returning 204 No Content.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | DELETE /videos/{id} with full DB cascade + MinIO cleanup | cce7873 | services/api/app/videos.py |
| 2 | Human verification of live API behavior | — | Pending checkpoint |

## What Was Built

### Modified Imports
- `from .storage import generate_presigned_url, generate_presigned_upload_url, get_minio_client`
  — added `get_minio_client` to use internal Minio client for deletion operations

### New Endpoint: `DELETE /videos/{id}`
- **Status:** 204 No Content on success
- **404:** When video ID does not exist in DB
- **401:** Automatically from router-level `Depends(require_token)` in `main.py` — no auth code in endpoint

### DB Deletion Flow (atomic via `conn.transaction()`)
1. `DELETE FROM face_detections WHERE frame_id IN (SELECT id FROM frames WHERE video_id = $1)`
2. `DELETE FROM detections WHERE frame_id IN (SELECT id FROM frames WHERE video_id = $1)`
3. `DELETE FROM frames WHERE video_id = $1`
4. `DELETE FROM videos WHERE id = $1`

### MinIO Cleanup (best-effort, after DB commit)
- **Video file:** `client.remove_object(MINIO_BUCKET_VIDEOS, video["minio_key"])`
- **Frame thumbnails:** `client.remove_objects(MINIO_BUCKET_FRAMES, iter(DeleteObject(r["minio_key"]) for r in frame_rows))`
- Errors logged as `WARNING` but never raised — DB deletion is authoritative

### Route Decorator Count
- Before: 7 (`@router.post`, `@router.get` ×5, `@router.get` for stream)
- After: **8** (`+@router.delete`)

## Deviations from Plan

None — plan executed exactly as written. The only deviation from the strict `require_token grep count = 0` check is that 2 pre-existing occurrences in the `get_upload_url` docstring (from Plan 06-01) remain; these are documentation-only comments with no functional auth code in videos.py.

## Known Stubs

None — endpoint performs real DB deletion and real MinIO object removal.

## Threat Flags

No new threat surface beyond what is documented in the plan's threat model:
- T-06-06 (Spoofing): Mitigated — `require_token` on `videos_router` in `main.py`; unauthenticated requests receive 401 before the route handler runs
- T-06-07 (Tampering): Accepted — UUID type coercion + parameterized SQL ($1) prevents injection

## Checkpoint Pending

**Task 2 — Human verify** requires running the live API:

```bash
# Test 1: 401 without token (DEL-05)
curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  http://localhost:8000/videos/00000000-0000-0000-0000-000000000000
# Expected: 401

# Test 2: 404 for unknown ID
curl -s -w "\n%{http_code}" -X DELETE \
  -H "Authorization: Bearer ${API_TOKEN}" \
  http://localhost:8000/videos/00000000-0000-0000-0000-000000000000
# Expected: 404 {"detail":"Video not found"}

# Test 3: 204 + DB cascade (DEL-03)
curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  -H "Authorization: Bearer ${API_TOKEN}" \
  http://localhost:8000/videos/<real-id>
# Expected: 204
```

Signal continuation with "approved" when all three pass.

## Self-Check: PASSED

- `services/api/app/videos.py` exists and parses cleanly (Python AST: syntax OK)
- 8 route decorators present (7 from Plan 06-01 + 1 new DELETE)
- `get_minio_client` appears 2 times (import line + call site)
- `conn.transaction()` appears 1 time
- All 4 `DELETE FROM` statements present: face_detections, detections, frames, videos
- `remove_object` (single) present for video file deletion
- `remove_objects` (bulk) present for frame thumbnail deletion
- `DeleteObject` imported and used in endpoint
- No functional `require_token` usage in videos.py (2 pre-existing docstring mentions only)
- Commit cce7873 exists in git log
