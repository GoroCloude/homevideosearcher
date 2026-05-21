---
phase: 05-video-upload
plan: 01
subsystem: ui, api
tags: [react, fastapi, minio, xhr, presigned-url, typescript]

# Dependency graph
requires:
  - phase: 04-web-ui
    provides: VideosPage, authFetch, addToast singleton, TanStack Query v5 patterns
  - phase: 01-foundation
    provides: MinIO storage, generate_presigned_url pattern, videos router with require_token
provides:
  - POST /api/videos/upload-url endpoint returning presigned MinIO PUT URL
  - generate_presigned_upload_url() helper in storage.py
  - VideoUploadButton.tsx React component with XHR upload and sequential queue
  - Upload progress bar (h-1) in VideosPage
  - scripts/setup-minio-cors.sh diagnostic script
affects: [deploy, operations, README]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - presigned-put-url: browser uploads directly to MinIO via XHR, API only generates HMAC-signed URL
    - xhr-upload-progress: XMLHttpRequest required (fetch has no native upload progress)
    - sequential-upload-queue: for...of with await (not Promise.all) for multi-file upload
    - callback-progress-pattern: onProgressChange(pct) prop; parent (VideosPage) owns progress state

key-files:
  created:
    - services/api/app/storage.py (generate_presigned_upload_url added)
    - services/web/src/components/VideoUploadButton.tsx
    - scripts/setup-minio-cors.sh
  modified:
    - services/api/app/videos.py
    - services/web/src/types/api.ts
    - services/web/src/api/videos.ts
    - services/web/src/pages/VideosPage.tsx
    - README.md

key-decisions:
  - "generate_presigned_upload_url uses get_public_minio_client() (not get_minio_client()) — URL must use MINIO_PUBLIC_ENDPOINT for browser resolvability"
  - "Upload progress uses XHR (not fetch) — fetch has no native upload progress API"
  - "Sequential queue via for...of + await — D-01 continues on per-file failure"
  - "Toast type 'info' for ingest-failure — 'warning' type does not exist in the toast system"
  - "Progress bar hidden at pct=0 and pct>=100 — D-09 avoids flicker at end of queue"
  - "Button shows 'N/M uploaded' summary after queue — D-02"

patterns-established:
  - "presigned-put-url: POST /videos/upload-url → XHR PUT → POST /ingest-api/ingest"
  - "onProgressChange callback: component accepts pct callback, parent owns state"
  - "generate_presigned_upload_url mirrors generate_presigned_url but with presigned_put_object + expires_minutes"

requirements-completed:
  - UPLOAD-01
  - UPLOAD-02
  - UPLOAD-03
  - UPLOAD-04
  - UPLOAD-05
  - UPLOAD-06

# Metrics
duration: 25min
completed: 2025-05-17
---

# Phase 5: Video Upload Summary

**Presigned MinIO PUT upload from browser via XHR with progress bar, sequential queue, 1 GB validation, and auto-ingest trigger**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3
- **Files modified:** 8

## Accomplishments

- Backend: `generate_presigned_upload_url()` in `storage.py` + `POST /videos/upload-url` endpoint with T1/T2 security (path traversal + scope lock)
- Frontend: `VideoUploadButton.tsx` with XHR upload, sequential multi-file queue, exact SPEC toast messages, 1 GB validation
- Integration: `h-1` progress bar in `VideosPage` between header and table; `VideoUploadButton` in header alongside video count
- Operations: `scripts/setup-minio-cors.sh` diagnostic script + README deployment note (D-04)
- TypeScript: compiles clean, no type errors

## Task Commits

1. **Task 1: Backend presigned upload URL endpoint** — `18da856`
2. **Task 2: Frontend foundation (types, hook, component)** — `04d87dc`
3. **Task 3: VideosPage integration + CORS script + README** — `1a6a31f`

## Files Created/Modified

- `services/api/app/storage.py` — added `generate_presigned_upload_url()` using `presigned_put_object` + `get_public_minio_client()`
- `services/api/app/videos.py` — added `UploadUrlRequest`/`UploadUrlResponse` models + `POST /upload-url` endpoint with `os.path.basename` sanitization
- `services/web/src/types/api.ts` — added `UploadUrlResponse` interface
- `services/web/src/api/videos.ts` — added `getUploadUrl()` function + `useUploadVideo()` hook
- `services/web/src/components/VideoUploadButton.tsx` — new component (created)
- `services/web/src/pages/VideosPage.tsx` — added `VideoUploadButton` + progress bar + `uploadProgress` state
- `scripts/setup-minio-cors.sh` — new idempotent CORS verification script (created)
- `README.md` — added Phase 5 deployment section (D-04)

## Decisions Made

- `generate_presigned_upload_url` uses `get_public_minio_client()` — internal Docker endpoint is not browser-resolvable; public endpoint required for presigned URLs
- XHR mandatory for upload progress — `fetch` has no native `upload.onprogress`; `authFetch` used only for API call, raw XHR for MinIO PUT
- `'info'` toast type for ingest-failure — `'warning'` type does not exist in the toast system

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

- Phase 5 feature is complete and committed; deploy to homeserver via `git pull && docker compose build && docker compose up -d`
- Run `bash scripts/setup-minio-cors.sh` after deploy to verify MinIO connectivity
- MinIO CORS is enabled by default on modern versions; script is diagnostic only

---
*Phase: 05-video-upload*
*Completed: 2025-05-17*
