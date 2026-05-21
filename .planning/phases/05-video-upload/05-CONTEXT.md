# Phase 5: Video Upload UI - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can upload one or more video files directly from the Videos page "Upload Video" button. Each file uploads directly from the browser to MinIO via a presigned PUT URL (no nginx proxy), then auto-ingests. A progress bar tracks overall queue progress. All outcomes are reported via toast notifications.

</domain>

<spec_lock>
## Requirements (locked via SPEC.md)

**6 requirements are locked.** See `05-SPEC.md` for full requirements, boundaries, and acceptance criteria.

Downstream agents MUST read `05-SPEC.md` before planning or implementing. Requirements are not duplicated here.

**In scope (from SPEC.md):**
- `POST /api/videos/upload-url` endpoint (API) — generates presigned MinIO PUT URL
- `generate_presigned_upload_url(bucket, key, expires_minutes)` helper in `storage.py`
- `VideoUploadButton` component — file picker, progress, queue management, toast calls
- `getUploadUrl(filename)` function + `useUploadVideo()` mutation hook in `videos.ts`
- Integration into `VideosPage.tsx` — button placement in header, video list invalidation after upload
- Client-side validation (size ≤ 1 GB, non-empty)
- Sequential multi-file queue (one file at a time)
- MinIO CORS configuration documented in `scripts/setup-minio-cors.sh`

**Out of scope (from SPEC.md):**
- Drag-and-drop zone — upload button/file picker only
- Upload progress persisted across page reload
- Resumable/chunked uploads for files > 1 GB
- Video transcoding or format conversion
- Presigned URL expiry configuration (1-hour TTL fixed)
- Upload history or audit log

</spec_lock>

<decisions>
## Implementation Decisions

### Queue failure handling
- **D-01:** When a file fails (PUT error or ingest trigger failure), show an error toast for that file and **continue** uploading remaining files in the queue. Do not abort the queue on a single failure.
- **D-02:** After the full queue finishes (all files processed, some possibly failed), the button shows a summary state: `"{N}/{total} uploaded"` (e.g. "2/3 uploaded"). This persists until the user picks new files or clicks away. Button resets to "Upload Video" when a new file selection is made.

### MinIO CORS setup
- **D-03:** Create `scripts/setup-minio-cors.sh` — a shell script containing `mc` (MinIO Client) commands to configure CORS on the MinIO `videos` bucket. This allows `PUT` requests from the UI's origin (`http://homevideosearcher.shumov.eu` and localhost for dev). Note: MinIO is external (not in docker-compose.yml), so CORS must be configured via mc CLI on the homeserver.
- **D-04:** The script is documented in the README deployment section — users must run it once after deploying Phase 5. It should be idempotent (safe to re-run).

### Component breakdown
- **D-05:** Extract upload logic into a standalone `services/web/src/components/VideoUploadButton.tsx` component. This follows the `EnrollmentDropzone.tsx` pattern (separate component file, self-contained state, `addToast` calls, props for callbacks).
- **D-06:** One plan file only (`05-01-PLAN.md`) covering the full phase: API endpoint, storage helper, API hook, `VideoUploadButton` component, `VideosPage` integration, and CORS setup script.

### Progress indicator design
- **D-07:** Show a progress bar (not just button text) during upload. The bar is a **thin horizontal bar (h-1) positioned between the Videos page header row and the table** — visually separates the action from the content without taking up vertical space.
- **D-08:** The progress bar tracks **overall queue progress** (total bytes across all files). For 3 × 100 MB files, the bar reaches 33% after file 1 completes, 66% after file 2, 100% after file 3. Progress is calculated as `bytesUploaded / totalBytes` across all queued files.
- **D-09:** The progress bar is only visible while an upload is in progress (hidden otherwise — no empty bar placeholder).
- **D-10:** Button text during upload: `"Uploading…"` (static, no % in button — the bar handles %). After queue completes: `"{N}/{total} uploaded"` (per D-02). Normal state: `"Upload Video"`.

### the agent's Discretion
- Exact Tailwind classes for the progress bar (color, animation, border-radius)
- Whether to use `<progress>` HTML element or a styled `<div>` for the bar
- How XHR `onprogress` state is tracked internally (useRef vs useState for performance)
- Exact error message wording for network failures (follow SPEC.md wording for the happy path and validation errors)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements and acceptance criteria
- `.planning/phases/05-video-upload/05-SPEC.md` — Locked requirements — MUST read before planning

### Existing patterns to follow
- `services/web/src/components/EnrollmentDropzone.tsx` — Upload component pattern (file input, submit button, `addToast`, rejection state)
- `services/web/src/api/videos.ts` — API hook pattern (`useReIngestVideo`, `authFetch`, `getSettings`)
- `services/api/app/storage.py` — Presigned URL generation pattern (`_public_client`, `generate_presigned_url`)
- `services/api/app/main.py` — Router registration with `Depends(require_token)`
- `services/web/src/api/client.ts` — `authFetch` and `getSettings` helpers
- `services/web/src/hooks/useToast.ts` — Toast system (module-level `addToast`)

### Pages to modify
- `services/web/src/pages/VideosPage.tsx` — Add VideoUploadButton to header, show progress bar between header and table

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `addToast(message, type)` from `useToast.ts` — used in EnrollmentDropzone; same pattern for upload success/error
- `authFetch(path, options)` from `api/client.ts` — for the `POST /api/videos/upload-url` request
- `getSettings()` from `api/client.ts` — to get `apiToken` and `apiBaseUrl` for manual fetch calls
- `useQueryClient().invalidateQueries({ queryKey: ['videos'] })` — existing pattern in `useReIngestVideo`; reuse in `useUploadVideo` after ingest trigger
- `fetch('/ingest-api/ingest', { method: 'POST', body: JSON.stringify({minio_key, force: true}) })` — already used in `reIngestVideo()`; reuse for auto-ingest trigger

### Established Patterns
- **XHR for upload**: `fetch` has no native upload progress — use `XMLHttpRequest` with `xhr.upload.addEventListener('progress', e => ...)` for the MinIO PUT. `authFetch` wraps `fetch` (not XHR), so the PUT to MinIO must be a raw `new XMLHttpRequest()` call (not `authFetch`).
- **Auth for API call**: `POST /api/videos/upload-url` uses `authFetch` (bearer token). The subsequent PUT to MinIO uses the presigned URL directly — no auth header needed (the URL is self-authenticating).
- **Router registration**: `app.include_router(videos_router, dependencies=[Depends(require_token)])` — the new `upload-url` endpoint is added to the existing `videos_router`, so it inherits bearer auth automatically.
- **`_public_client` for presigned URL**: `generate_presigned_upload_url` must use `get_public_minio_client()` (not `get_minio_client()`) so the returned URL uses `MINIO_PUBLIC_ENDPOINT` and is browser-resolvable. Same constraint as `generate_presigned_url`.

### Integration Points
- `POST /api/videos/upload-url` → new endpoint in `services/api/app/videos.py` (existing router)
- `generate_presigned_upload_url(bucket, key, expires_minutes)` → new helper in `services/api/app/storage.py` using `minio.presigned_put_object()`
- `VideoUploadButton` → imported into `VideosPage.tsx`; placed in the header `<div className="flex items-center justify-between mb-5">` alongside the title and video count
- Progress bar → rendered between the header `<div>` and the table `<div>` in `VideosPage.tsx`; controlled by state passed down from VideoUploadButton (or lifted to VideosPage)

</code_context>

<specifics>
## Specific Ideas

- Progress bar position: `h-1` thin bar in the gap between the Videos page header div (`mb-5`) and the table — no extra margin/padding needed, just conditional render when `progress > 0 && progress < 100`
- Queue summary button text: `"{N}/{total} uploaded"` where N = files that succeeded (PUT + ingest both ok), total = all selected files including failed ones
- MinIO CORS `mc` command reference: `mc anonymous set upload myminio/videos` for public PUT, OR use `mc admin bucket-cors set` if MinIO version supports it. Script should detect MinIO version and use the appropriate command.
- The `ingest` call after upload uses `force: true` always — consistent with Re-ingest button behavior; prevents silent skip on overwrite

</specifics>

<deferred>
## Deferred Ideas

- Drag-and-drop zone for video upload — SPEC.md explicitly excludes this; can be added in a future phase if needed
- Per-file progress bars — user chose overall queue progress; individual file progress is a future enhancement
- Upload history/audit log — out of scope per SPEC.md

</deferred>

---

*Phase: 5-video-upload*
*Context gathered: 2026-05-27*
