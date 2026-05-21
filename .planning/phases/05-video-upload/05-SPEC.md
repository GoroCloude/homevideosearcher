# Phase 5: Video Upload — Specification

**Created:** 2026-05-27
**Ambiguity score:** 0.10 (gate: ≤ 0.20)
**Requirements:** 6 locked

## Goal

Users can upload one or more video files directly from the Videos page UI; each file is stored in MinIO and ingestion starts automatically — without requiring access to the MinIO console.

## Background

Today, adding a new video to the system requires two out-of-band steps: (1) uploading the file to MinIO using the MinIO console or CLI, then (2) triggering ingestion manually via Re-ingest or the n8n webhook. The Videos page (`VideosPage.tsx`) has no upload control — it only shows the existing video list and a Re-ingest button per row. This phase adds an "Upload Video" button to the Videos page header that uploads files directly from the browser to MinIO via presigned PUT URLs, then auto-triggers ingestion for each file.

The API already has a `generate_presigned_url` helper in `storage.py` for GET URLs. A new presigned PUT variant is needed. The existing `POST /ingest-api/ingest` (proxied through nginx) handles ingestion; the upload flow reuses it after PUT completes.

## Requirements

1. **Upload URL endpoint**: A new API endpoint generates a MinIO presigned PUT URL for a given filename.
   - Current: `storage.py` only has `generate_presigned_url` (GET); no PUT presigned URL generation exists; no `/videos/upload-url` endpoint exists
   - Target: `POST /api/videos/upload-url` accepts `{ "filename": "video.mp4" }` and returns `{ "url": "<presigned-put-url>", "key": "videos/video.mp4", "expires_in": 3600 }`; the URL is generated with `_public_client` so it uses `MINIO_PUBLIC_ENDPOINT` (browser-resolvable); requires bearer auth
   - Acceptance: Calling `POST /api/videos/upload-url` with filename `"test.mp4"` returns HTTP 200 with a non-empty `url` field containing `videos/test.mp4` in its path; an HTTP PUT to that URL with a small binary payload results in the object existing in MinIO

2. **Upload button UI**: An "Upload Video" button appears on the Videos page header.
   - Current: `VideosPage.tsx` has no upload control — only title + video count in the header row
   - Target: An "Upload Video" button appears at the top-right of the Videos page (next to the video count); clicking it opens a native file picker filtered to video files (`video/*`); the button is disabled and shows "Uploading…" while any upload is in progress
   - Acceptance: Button is visible on the Videos page; clicking it opens the OS file picker; button text changes to "Uploading…" during any active upload and reverts to "Upload Video" when the queue is empty

3. **Client-side validation**: Files that fail validation are rejected before any network request.
   - Current: No upload UI exists; no validation logic
   - Target: Files exceeding 1 GB (1,073,741,824 bytes) or with zero size are rejected immediately; for each rejected file a toast error is shown: `"'{filename}' is too large (max 1 GB)"` or `"'{filename}' is empty"`; rejected files do not trigger any API call
   - Acceptance: Selecting a file > 1 GB shows the size-error toast and makes zero network requests; selecting a zero-byte file shows the empty-file toast; selecting a valid file proceeds to upload

4. **Direct MinIO upload with progress**: Each file uploads directly from the browser to MinIO via the presigned PUT URL, with a visible progress bar.
   - Current: No upload mechanism; nginx has `client_max_body_size 50m` — cannot proxy GB-level files
   - Target: Upload uses `XMLHttpRequest.upload.onprogress` to track bytes sent; a progress indicator (e.g. "Uploading… 42%") replaces the button text during upload; multiple files are uploaded sequentially (one at a time), not in parallel; if duplicate filename exists in MinIO, it is overwritten (same key reused)
   - Acceptance: For a 10–50 MB test video, the progress indicator advances incrementally before hitting 100%; a second file in the queue does not start until the first finishes

5. **Auto-ingest after upload**: Ingestion is triggered automatically for each successfully uploaded file.
   - Current: Ingestion requires a manual Re-ingest click or n8n webhook; no automatic trigger after UI upload
   - Target: After each successful MinIO PUT, the UI calls `POST /ingest-api/ingest` with `{ "minio_key": "videos/{filename}", "force": true }` (force=true handles re-upload overwrites); `force: true` ensures duplicate filenames are re-processed without manual intervention
   - Acceptance: Uploading a new video causes it to appear in the Videos list with status `processing` or `done` within 10 seconds, without the user clicking Re-ingest; uploading a previously-ingested filename (overwrite) causes the video row status to cycle back through `processing` → `done`

6. **Success/error toast feedback**: Every upload outcome (success or failure) is communicated via the existing toast system.
   - Current: No upload feedback; toast system exists (`useToast` hook + `Toast.tsx` component)
   - Target:
     - Success: `"'{filename}' uploaded — ingestion started"` (green toast)
     - Ingest-trigger failure (upload succeeded but `/ingest` call failed): `"'{filename}' uploaded but ingestion could not be started"` (warning toast)
     - PUT failure: `"Upload failed for '{filename}': {error message}"` (red toast)
   - Acceptance: A successful upload shows the green success toast; a simulated `/ingest` failure (wrong URL) shows the warning toast; the video list is invalidated and refreshes after each successful ingest trigger

## Boundaries

**In scope:**
- `POST /api/videos/upload-url` endpoint (API) — generates presigned MinIO PUT URL
- `generate_presigned_upload_url(bucket, key, expires_minutes)` helper in `storage.py`
- `VideoUploadButton` component (`services/web/src/components/VideoUploadButton.tsx`) — file picker, progress, queue management, toast calls
- `getUploadUrl(filename)` function + `useUploadVideo()` mutation hook in `videos.ts`
- Integration into `VideosPage.tsx` — button placement in header, video list invalidation after upload
- Client-side validation (size ≤ 1 GB, non-empty)
- Sequential multi-file queue (one file at a time)
- MinIO CORS configuration to allow PUT from the UI origin — documented in ops guide

**Out of scope:**
- Drag-and-drop zone on the Videos page — upload button/file picker only (Phase 5 scope is minimal viable upload)
- Upload progress persisted across page reload — in-memory progress only
- Resumable/chunked uploads for files > 1 GB — 1 GB cap covers typical home video files; chunking is a separate backlog item
- Video transcoding or format conversion — ingestion-worker uses FFmpeg on the raw file as-is
- Presigned URL expiry configuration — 1-hour TTL is sufficient; no user-configurable TTL
- Upload history or audit log — not required for v1.0

## Constraints

- Upload must go browser → MinIO directly (presigned PUT) to avoid nginx's `client_max_body_size` limit; the API never proxies video bytes
- MinIO must have CORS configured to allow `PUT` requests from the UI's origin (`http://homevideosearcher.shumov.eu` and `http://localhost:5173` for dev); without CORS the browser will block the PUT; this must be documented and set up as part of deployment
- `generate_presigned_upload_url` must use `_public_client` (configured with `MINIO_PUBLIC_ENDPOINT`), not `_client` — same pattern as `generate_presigned_url` in `storage.py`
- Multiple files upload sequentially (not parallel) — prevents memory pressure on the 8 GB homeserver
- `force: true` is always sent to `/ingest` — consistent with Re-ingest behavior; avoids silent skip on overwrite
- Auth token is required for `POST /api/videos/upload-url` (same bearer auth as all other protected endpoints)

## Acceptance Criteria

- [ ] `POST /api/videos/upload-url` with `{ "filename": "test.mp4" }` returns HTTP 200 with a presigned PUT URL containing `videos/test.mp4` in the path; unauthenticated request returns 401
- [ ] PUT request to the returned presigned URL with a binary payload succeeds (HTTP 200) and the object appears in MinIO under `videos/test.mp4`
- [ ] "Upload Video" button appears at the top-right of the Videos page header
- [ ] Selecting a file > 1 GB shows a toast error and makes zero network requests
- [ ] For a valid video file, progress indicator shows upload percentage advancing from 0% to 100%
- [ ] Multiple files in a single selection upload one at a time (second upload does not start before first finishes)
- [ ] After upload completes, `POST /ingest-api/ingest` is called with `minio_key: "videos/{filename}"` and `force: true`
- [ ] A new video appears in the Videos list with `processing` or `done` status within 10 seconds of upload completing — without manual Re-ingest click
- [ ] Success toast `"'{filename}' uploaded — ingestion started"` is shown after each file completes
- [ ] Uploading a video that already exists in MinIO overwrites the file and re-processes it (status cycles: `done` → `processing` → `done`)
- [ ] Upload button is disabled and shows "Uploading…" while any upload is in progress; reverts to "Upload Video" when queue is empty

## Ambiguity Report

| Dimension           | Score | Min  | Status | Notes                                                    |
|---------------------|-------|------|--------|----------------------------------------------------------|
| Goal Clarity        | 0.95  | 0.75 | ✓      | Clear: upload → MinIO presigned PUT → auto-ingest        |
| Boundary Clarity    | 0.90  | 0.70 | ✓      | 1 GB cap, multi-file sequential, videos/ prefix defined  |
| Constraint Clarity  | 0.85  | 0.65 | ✓      | Presigned PUT, CORS note, public client pattern clear    |
| Acceptance Criteria | 0.88  | 0.70 | ✓      | 11 falsifiable pass/fail criteria                        |
| **Ambiguity**       | 0.10  | ≤0.20| ✓      |                                                          |

## Interview Log

| Round | Perspective      | Question summary                        | Decision locked                                                   |
|-------|------------------|-----------------------------------------|-------------------------------------------------------------------|
| 1     | Researcher       | What happens after upload? Where in UI? | Auto-ingest immediately; "Upload Video" button at top of page    |
| 2     | Simplifier       | File size limit? Multi-file? MinIO path?| 1 GB max; multi-file queue allowed; `videos/` prefix             |
| 3     | Boundary Keeper  | Upload method? Progress? Duplicate names?| Presigned PUT (direct to MinIO); progress bar; overwrite existing |
| 4     | Failure Analyst  | Success/error UX? List refresh?         | Toast for all outcomes; video list auto-refreshes after ingest    |

---

*Phase: 05-video-upload*
*Spec created: 2026-05-27*
*Next step: /gsd-discuss-phase 5 — implementation decisions (component design, XHR vs fetch, CORS setup)*
