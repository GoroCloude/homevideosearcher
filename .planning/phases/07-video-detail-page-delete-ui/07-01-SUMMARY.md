---
phase: "07"
plan: "01"
subsystem: web-api-layer
tags: [typescript, tanstack-query, api-client, types]
dependency-graph:
  requires: []
  provides: [VideoDetailItem, VideoDetectionItem, VideoFaceItem, useVideoDetail, useVideoDetections, useVideoFaces, useDeleteVideo]
  affects: [services/web/src/types/api.ts, services/web/src/api/videos.ts]
tech-stack:
  added: []
  patterns: [useQuery with enabled guard, useMutation with onSuccess cache invalidation]
key-files:
  modified:
    - services/web/src/types/api.ts
    - services/web/src/api/videos.ts
decisions:
  - deleteVideo returns Promise<void> and does not call .json() — DELETE returns 204 No Content
  - useDeleteVideo uses removeQueries (not invalidateQueries) for the specific video's detail cache
metrics:
  duration: "~3 minutes"
  completed: "2025-01-31"
  tasks-completed: 2
  files-modified: 2
---

# Phase 7 Plan 1: Types + API Client Functions + Hooks Summary

**One-liner:** Added three typed API interfaces and four TanStack Query hooks (detail/detections/faces/delete) as the data-layer foundation for the Video Detail Page.

## What Was Implemented

### `services/web/src/types/api.ts`
Three new interfaces appended after `UploadUrlResponse`:

- **`VideoDetailItem`** — Full video record including `filename`, `stream_url`, status, timestamps, and aggregate counts.
- **`VideoDetectionItem`** — Per-detection row with `frame_id` (UUID), `ts_ms`, `thumbnail_url` (presigned), `label`, `confidence`, and `bbox_json`.
- **`VideoFaceItem`** — Per-face appearance row with `frame_id` (UUID), `ts_ms`, `thumbnail_url` (presigned), `person_name` (already resolved by API), and `appearance_count`.

### `services/web/src/api/videos.ts`
Updated type import to include the three new interfaces. Appended:

**Async functions (4):**
- `getVideo(id)` → `GET /videos/{id}` → `VideoDetailItem`
- `getVideoDetections(id)` → `GET /videos/{id}/detections` → `VideoDetectionItem[]`
- `getVideoFaces(id)` → `GET /videos/{id}/faces` → `VideoFaceItem[]`
- `deleteVideo(id)` → `DELETE /videos/{id}` → `void` (204 No Content, no `.json()` call)

**Hooks (4):**
- `useVideoDetail(id)` — `queryKey: ['video', id]`, `staleTime: 15_000`, `enabled: !!apiToken && !!id`
- `useVideoDetections(id)` — `queryKey: ['video-detections', id]`
- `useVideoFaces(id)` — `queryKey: ['video-faces', id]`
- `useDeleteVideo()` — mutation that on success invalidates `['videos']`, `['search']`, `['clusters']` and **removes** (not invalidates) `['video', id]`

## Files Changed

| File | Change | Lines added |
|------|--------|-------------|
| `services/web/src/types/api.ts` | Appended 3 interfaces | +36 |
| `services/web/src/api/videos.ts` | Updated import, appended 4 functions + 4 hooks | +70 |

**Total:** 106 insertions, 1 deletion (import line expanded from 1 to 7 lines).

## TypeScript Verification

```
npx tsc --noEmit
Exit code: 0 — zero errors
```

## Commit

**Hash:** `33ab8a6`  
**Message:** `feat(web): add VideoDetail/Detection/Face types and API hooks`

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `services/web/src/types/api.ts` — FOUND, contains all three new interfaces
- `services/web/src/api/videos.ts` — FOUND, contains all four functions and four hooks
- Commit `33ab8a6` — FOUND in git log
- TypeScript: zero errors
