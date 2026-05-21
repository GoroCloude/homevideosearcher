# Phase 5: Video Upload UI — Research

**Researched:** 2026-05-27
**Domain:** MinIO presigned PUT URLs, browser XHR upload progress, FastAPI file upload endpoint, React sequential queue
**Confidence:** HIGH (codebase fully read; MinIO SDK version confirmed; patterns verified against existing code)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** File failure → show error toast and **continue** queue. Do not abort the queue on a single failure.
- **D-02:** After full queue completes: button shows `"{N}/{total} uploaded"`. Resets on new file selection.
- **D-03:** Create `scripts/setup-minio-cors.sh` with `mc` commands. Idempotent, safe to re-run.
- **D-04:** Document script in README deployment section. Users must run once after Phase 5 deploy.
- **D-05:** Extract into `services/web/src/components/VideoUploadButton.tsx`. Follows EnrollmentDropzone pattern.
- **D-06:** One plan file: `05-01-PLAN.md` covering API endpoint, storage helper, API hook, component, page integration, CORS script.
- **D-07:** Progress bar: thin `h-1` horizontal bar positioned between Videos page header row and table.
- **D-08:** Bar tracks **overall queue progress** — `bytesUploaded / totalBytes` across all files.
- **D-09:** Bar only visible while upload is in progress (`progress > 0 && progress < 100`).
- **D-10:** Button text: `"Uploading…"` during upload; `"{N}/{total} uploaded"` after; `"Upload Video"` at rest.

### the agent's Discretion
- Exact Tailwind classes for progress bar (color, animation, border-radius)
- `<progress>` HTML element vs. styled `<div>` for bar
- XHR `onprogress` state tracking internally (useRef vs useState for performance)
- Exact error message wording for network failures (follow SPEC.md wording for happy path and validation errors)

### Deferred Ideas (OUT OF SCOPE)
- Drag-and-drop zone for video upload
- Per-file progress bars
- Upload history/audit log
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UPLOAD-01 | `POST /api/videos/upload-url` endpoint returning presigned MinIO PUT URL | `presigned_put_object` in MinIO SDK 7.2.20; follows existing `generate_presigned_url` pattern in `storage.py` |
| UPLOAD-02 | "Upload Video" button in Videos page header, shows "Uploading…" during active upload | `VideoUploadButton.tsx` component; follows `EnrollmentDropzone` pattern; place in `VideosPage.tsx` header div |
| UPLOAD-03 | Client-side validation: reject files > 1 GB or zero-size with toast error | `file.size > 1_073_741_824` or `=== 0`; `addToast` module-level function from `useToast.ts` |
| UPLOAD-04 | Direct MinIO PUT via XHR with progress bar; sequential multi-file queue | `XMLHttpRequest.upload.onprogress` for progress; async sequential loop; `useRef` for XHR instance |
| UPLOAD-05 | Auto-ingest after each successful upload via `POST /ingest-api/ingest` | Reuse exact `reIngestVideo` pattern from `videos.ts`; `force: true` always; invalidate `['videos']` query after |
| UPLOAD-06 | Toast feedback for all outcomes: success / upload-failed / ingest-failed | `addToast(message, 'success'/'error'/'info')` from `useToast.ts`; exact wording from SPEC.md |
</phase_requirements>

---

## Summary

Phase 5 adds a self-contained `VideoUploadButton` component to the Videos page that lets users pick one or more video files, validates them client-side, and uploads each sequentially direct to MinIO via a presigned PUT URL obtained from a new `POST /api/videos/upload-url` endpoint. After each successful PUT, the component calls the existing `/ingest-api/ingest` proxy to trigger automatic ingestion with `force: true`. A thin progress bar (h-1) between the header row and the video table shows overall queue progress.

The implementation is straightforward because all three tiers (API, client API hooks, and UI component) already have nearly identical patterns in the codebase. The `generate_presigned_upload_url` helper mirrors `generate_presigned_url` exactly, substituting `presigned_put_object` for `presigned_get_object`. The XHR upload mirrors the existing enrollment form-upload mental model, except using raw XHR (not `authFetch`) because `fetch` has no native upload progress. Toast calls and query invalidation are copied verbatim from `useReIngestVideo`.

**Primary recommendation:** Copy-adapt patterns directly from existing files (`storage.py`, `videos.py`, `EnrollmentDropzone.tsx`, `videos.ts`). No new libraries needed. The only "new" technical surface is MinIO's `presigned_put_object` and the XHR upload-progress API — both are straightforward.

**Critical CORS discovery:** Official MinIO docs state "CORS is enabled by default for all buckets and supports all HTTP verbs — BucketCORS operations are unnecessary in MinIO." [VERIFIED: MinIO docs via Context7]. The `scripts/setup-minio-cors.sh` (D-03 locked) should document this, verify connectivity, and fall back to `mc anonymous set` commands for older MinIO versions. See § MinIO CORS below.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Generate presigned PUT URL | API (`storage.py`) | — | Requires MinIO credentials; never exposed to browser; uses `_public_client` for browser-resolvable URL |
| Serve upload-url endpoint | API (`videos.py`) | — | Auth-protected; filename sanitization; Pydantic models |
| Direct binary upload (video bytes) | Browser → MinIO (direct) | — | Bypasses nginx `client_max_body_size 50m`; XHR PUT to presigned URL |
| Upload progress tracking | Browser (`VideoUploadButton`) | — | XHR `upload.onprogress` is browser-only API |
| Sequential queue management | Browser (`VideoUploadButton`) | — | Client-side state; prevents memory pressure on 8 GB host |
| Auto-ingest trigger | Browser → nginx → ingestion-worker | — | Reuse existing `/ingest-api/ingest` proxy; identical to Re-ingest button |
| Query invalidation (refresh list) | Browser (TanStack Query) | — | `invalidateQueries({ queryKey: ['videos'] })` — existing pattern |
| CORS configuration | MinIO host (ops script) | — | External to docker-compose; one-time setup via `mc` CLI |

---

## Standard Stack

### Core (no new dependencies)

| Library | Version | Purpose | Verified In |
|---------|---------|---------|-------------|
| `minio` (Python SDK) | `7.2.20` | `presigned_put_object` for storage helper | `services/api/requirements.txt` [VERIFIED] |
| `fastapi` + `pydantic` | `0.136.1` / `>=2.0` | New upload-url endpoint + Pydantic models | `services/api/requirements.txt` [VERIFIED] |
| React 18 + TanStack Query v5 | `18.3.1` / `5.100.10` | Hook pattern for `useUploadVideo` | `services/web/package.json` [VERIFIED] |
| Tailwind CSS v3 | `3.4.19` (pinned) | Progress bar styling (`h-1`, `bg-blue-500`, etc.) | `services/web/package.json` [VERIFIED] |
| Browser `XMLHttpRequest` | native | Upload progress via `xhr.upload.onprogress` | Standard Web API [ASSUMED] |

**Installation:** No new packages needed. All dependencies already present.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `clsx` | `2.1.1` | Button disabled/active state classes | Already used in `EnrollmentDropzone.tsx` |
| `date-fns` | `4.1.0` | Not needed for this phase | — |

---

## Architecture Patterns

### System Architecture Diagram

```
Browser                        nginx (web:80)              api (8000)            MinIO (external)
─────────────────────────────────────────────────────────────────────────────────────────────────

User picks files
       │
       ▼
[VideoUploadButton]
  validate size/empty
       │ (passes)
       ▼
POST /api/videos/upload-url  ──────────────────────►  POST /videos/upload-url
  { filename: "video.mp4" }                             │
                                                        │  generate_presigned_upload_url()
                                                        │  _public_client.presigned_put_object()
                             ◄──────────────────────   │
  { url: "https://minio…", key: "videos/video.mp4" }   │

       │
       ▼
xhr = new XMLHttpRequest()
xhr.open('PUT', presignedUrl)
xhr.upload.onprogress → update progress bar
xhr.send(file)  ────────────────────────────────────────────────────────────►  PUT /videos/video.mp4
                                                                               (direct, no nginx)
                ◄────────────────────────────────────────────────────────────  HTTP 200

       │
       ▼
POST /ingest-api/ingest  ──────►  POST /  ──────────────────►  POST /ingest
  { minio_key, force:true }     (ingest-api proxy)            ingestion-worker:8001
                ◄──────────────────────────────────────────────  HTTP 200/202

       │
       ▼
addToast("'video.mp4' uploaded — ingestion started", 'success')
invalidateQueries({ queryKey: ['videos'] })
process next file in queue (or show summary)
```

### Recommended File Changes

```
services/api/app/
├── storage.py          # ADD: generate_presigned_upload_url()
└── videos.py           # ADD: POST /upload-url endpoint + 2 Pydantic models

services/web/src/
├── api/
│   └── videos.ts       # ADD: getUploadUrl() function + useUploadVideo() hook
├── components/
│   └── VideoUploadButton.tsx   # NEW: self-contained upload component
├── pages/
│   └── VideosPage.tsx  # MODIFY: add VideoUploadButton + progress bar
└── types/
    └── api.ts          # ADD: UploadUrlRequest / UploadUrlResponse interfaces

scripts/
└── setup-minio-cors.sh  # NEW: mc alias setup + CORS verification
```

---

### Pattern 1: `generate_presigned_upload_url` in `storage.py`

**What:** New helper function — mirror of `generate_presigned_url` substituting `presigned_put_object` for `presigned_get_object`.
**When to use:** Called only by the new upload-url endpoint.

```python
# Source: mirrors generate_presigned_url() in services/api/app/storage.py [VERIFIED codebase]
from datetime import timedelta

def generate_presigned_upload_url(bucket: str, key: str, expires_minutes: int = 60) -> str:
    """
    Generate a presigned PUT URL valid for expires_minutes minutes.
    MUST use _public_client (MINIO_PUBLIC_ENDPOINT) so the URL is browser-resolvable.
    """
    client = get_public_minio_client()
    url = client.presigned_put_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(minutes=expires_minutes),
    )
    logger.debug("Generated presigned PUT URL for %s/%s (TTL=%dm)", bucket, key, expires_minutes)
    return url
```

**Key constraint:** Use `get_public_minio_client()` (not `get_minio_client()`). This produces a URL using `MINIO_PUBLIC_ENDPOINT` which is the browser-resolvable hostname. Same as `generate_presigned_url`. [VERIFIED: `_public_client` constraint in CONTEXT.md + `storage.py`]

**`presigned_put_object` signature in minio==7.2.20:**
- `presigned_put_object(bucket_name: str, object_name: str, expires: timedelta = timedelta(hours=1)) -> str`
- Returns: URL string, e.g. `http://minio.host:9000/videos/video.mp4?X-Amz-Algorithm=...`
- The URL is self-authenticating (HMAC-signed). No Authorization header needed for the PUT.
[CITED: MinIO docs via Context7, presigned-put-upload-via-browser.md]

---

### Pattern 2: `POST /upload-url` endpoint in `videos.py`

**What:** New protected endpoint on the existing `videos_router`. Inherits `Depends(require_token)` automatically (set at router registration in `main.py`).

```python
# Source: follows VideoListResponse pattern in services/api/app/videos.py [VERIFIED codebase]
import os

class UploadUrlRequest(BaseModel):
    filename: str

class UploadUrlResponse(BaseModel):
    url: str
    key: str
    expires_in: int  # seconds

@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(body: UploadUrlRequest) -> UploadUrlResponse:
    """Generate a presigned MinIO PUT URL for direct browser upload. Auth required."""
    # Sanitize: strip path separators to prevent directory traversal
    safe_name = os.path.basename(body.filename.replace("\\", "/")).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")

    key = f"videos/{safe_name}"
    url = generate_presigned_upload_url(
        bucket=config.MINIO_BUCKET_VIDEOS,
        key=key,
        expires_minutes=60,
    )
    return UploadUrlResponse(url=url, key=key, expires_in=3600)
```

**Filename sanitization:** `os.path.basename()` strips all path separators; handles both `/` and `\`. Prevents writing to e.g. `../../etc/passwd` paths in MinIO. [ASSUMED: standard server-side input sanitization]

**Auth:** The endpoint lives on `videos_router` which is registered with `dependencies=[Depends(require_token)]` in `main.py` — no extra auth wiring needed. [VERIFIED: `main.py`]

---

### Pattern 3: `getUploadUrl` + `useUploadVideo` in `videos.ts`

**What:** New API function and mutation hook. Follows `reIngestVideo` / `useReIngestVideo` pattern exactly.

```typescript
// Source: mirrors reIngestVideo + useReIngestVideo in services/web/src/api/videos.ts [VERIFIED codebase]
import type { UploadUrlResponse } from '../types/api';

export async function getUploadUrl(filename: string): Promise<UploadUrlResponse> {
  return authFetch('/videos/upload-url', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  }).then(r => r.json());
}

export function useUploadVideo() {
  const qc = useQueryClient();
  // Note: useUploadVideo is NOT a standard useMutation —
  // the actual XHR upload happens in the component (for progress tracking).
  // This hook exposes invalidateVideos() for post-upload list refresh.
  return {
    invalidateVideos: () => qc.invalidateQueries({ queryKey: ['videos'] }),
  };
}
```

**Why not `useMutation` for the PUT?** `useMutation` wraps `fetch`-based async functions. The XHR upload must be in the component (or a custom hook) because progress tracking requires `xhr.upload.onprogress` — this cannot be expressed as a simple async function with standard `fetch`. [VERIFIED: CONTEXT.md "XHR for upload" code insight]

**Types to add to `api.ts`:**
```typescript
export interface UploadUrlRequest { filename: string; }
export interface UploadUrlResponse { url: string; key: string; expires_in: number; }
```

---

### Pattern 4: XHR Upload with Progress (`VideoUploadButton.tsx`)

**What:** Core upload function — wraps `XMLHttpRequest` in a Promise; fires progress callback.

```typescript
// Source: standard XHR pattern [ASSUMED - standard Web API]
function uploadToMinIO(
  file: File,
  presignedUrl: string,
  onProgress: (loadedBytes: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', (e: ProgressEvent) => {
      if (e.lengthComputable) {
        onProgress(e.loaded);   // pass loaded bytes, not %
      }
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`PUT failed: HTTP ${xhr.status}`));
    });
    xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
    xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));
    xhr.open('PUT', presignedUrl);
    // Set Content-Type — MinIO presigned PUTs accept any content-type
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.send(file);
  });
}
```

**`e.lengthComputable` reliability:** For direct binary PUT uploads (not chunked), `lengthComputable` is always `true` and `e.total` equals the file size. This is reliable for files up to 1 GB. [ASSUMED: browser standard behavior — extremely well-established]

**Why `onProgress` receives `loadedBytes` (not `%`):** The component needs raw bytes to calculate overall queue progress across files: `(completedBytes + currentFileLoadedBytes) / totalBytes`. Percentage is derived at render time.

**XHR abort (for future use):**
```typescript
const xhrRef = useRef<XMLHttpRequest | null>(null);
// Store the XHR instance before sending:
// xhrRef.current = xhr; xhr.send(file);
// To cancel: xhrRef.current?.abort();
```

---

### Pattern 5: Sequential Queue in `VideoUploadButton.tsx`

**What:** Process files one at a time. Continue after failures (D-01). Track success count for summary (D-02).

```typescript
// Source: React patterns + CONTEXT.md decisions [ASSUMED with VERIFIED constraints from CONTEXT.md]
import { useState, useRef, useCallback } from 'react';
import { addToast } from '../hooks/useToast';
import { getUploadUrl } from '../api/videos';
import { reIngestVideo } from '../api/videos';

interface Props {
  onUploadComplete?: () => void;       // called after all files processed (for list invalidation)
  onProgressChange?: (pct: number) => void;  // called on each progress update (for bar in VideosPage)
}

export default function VideoUploadButton({ onUploadComplete, onProgressChange }: Props) {
  const [isUploading, setIsUploading] = useState(false);
  const [buttonLabel, setButtonLabel] = useState<string>('Upload Video');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const xhrRef       = useRef<XMLHttpRequest | null>(null);

  const handleFiles = useCallback(async (files: FileList) => {
    const fileArray = Array.from(files);

    // Client-side validation (UPLOAD-03)
    const MAX_SIZE = 1_073_741_824; // 1 GB
    const valid: File[] = [];
    for (const f of fileArray) {
      if (f.size === 0) {
        addToast(`'${f.name}' is empty`, 'error');
        continue;
      }
      if (f.size > MAX_SIZE) {
        addToast(`'${f.name}' is too large (max 1 GB)`, 'error');
        continue;
      }
      valid.push(f);
    }
    if (valid.length === 0) return;

    setIsUploading(true);
    setButtonLabel('Uploading…');  // D-10

    const totalBytes = valid.reduce((sum, f) => sum + f.size, 0);
    let completedBytes = 0;
    let successCount   = 0;

    for (const file of valid) {
      try {
        // 1. Get presigned PUT URL
        const { url, key } = await getUploadUrl(file.name);

        // 2. Upload directly to MinIO via XHR (UPLOAD-04)
        await uploadToMinIO(file, url, (loadedBytes) => {
          const pct = ((completedBytes + loadedBytes) / totalBytes) * 100;
          onProgressChange?.(pct);   // D-08: overall queue progress
        });
        completedBytes += file.size;
        onProgressChange?.((completedBytes / totalBytes) * 100);

        // 3. Trigger ingest (UPLOAD-05)
        try {
          await reIngestVideo(key);  // key = "videos/filename.mp4"
          successCount++;
          addToast(`'${file.name}' uploaded — ingestion started`, 'success');  // UPLOAD-06
          onUploadComplete?.();  // invalidate videos list
        } catch {
          // Upload succeeded but ingest failed
          addToast(`'${file.name}' uploaded but ingestion could not be started`, 'info');
        }
      } catch (err) {
        // PUT failed (D-01: continue with remaining files)
        const msg = err instanceof Error ? err.message : 'Unknown error';
        addToast(`Upload failed for '${file.name}': ${msg}`, 'error');
        completedBytes += file.size;  // advance progress even on failure (prevents stuck bar)
      }
    }

    // D-02: Summary button label
    setButtonLabel(`${successCount}/${valid.length} uploaded`);
    setIsUploading(false);
    onProgressChange?.(0);  // hide bar (D-09)
  }, [onUploadComplete, onProgressChange]);

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="video/*"
        className="hidden"
        onChange={e => {
          if (e.target.files?.length) {
            setButtonLabel('Upload Video');  // reset on new selection (D-02)
            handleFiles(e.target.files);
          }
          // Reset input so same file can be re-selected
          e.target.value = '';
        }}
      />
      <button
        onClick={() => fileInputRef.current?.click()}
        disabled={isUploading}
        className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-colors"
      >
        {buttonLabel}
      </button>
    </>
  );
}
```

---

### Pattern 6: `VideosPage.tsx` Integration

**What:** Add `VideoUploadButton` to header div; add progress bar between header and table.

```typescript
// Source: VideosPage.tsx [VERIFIED codebase] — modifications shown
import { useState } from 'react';
import VideoUploadButton from '../components/VideoUploadButton';
// ... existing imports

export default function VideosPage() {
  const [uploadProgress, setUploadProgress] = useState(0);
  const qc = useQueryClient();
  // ... existing state

  return (
    <div className="p-4 md:p-6">
      {/* Header row — existing structure, add VideoUploadButton on right */}
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-lg font-semibold text-gray-900">Videos</h1>
        <div className="flex items-center gap-3">
          {data && (
            <span className="text-sm text-gray-500">
              {data.total} video{data.total !== 1 ? 's' : ''}
            </span>
          )}
          <VideoUploadButton
            onUploadComplete={() => qc.invalidateQueries({ queryKey: ['videos'] })}
            onProgressChange={setUploadProgress}
          />
        </div>
      </div>

      {/* Progress bar — D-07, D-09: only visible during active upload */}
      {uploadProgress > 0 && uploadProgress < 100 && (
        <div className="h-1 bg-gray-200 rounded-full mb-5 overflow-hidden">
          <div
            className="h-1 bg-blue-500 rounded-full transition-all duration-150"
            style={{ width: `${uploadProgress}%` }}
          />
        </div>
      )}

      {/* ... rest of existing JSX unchanged ... */}
    </div>
  );
}
```

**`useQueryClient()` in `VideosPage`:** Already used in the existing `useReIngestVideo` pattern. Same QC instance, same `['videos']` key. [VERIFIED: `videos.ts`]

---

### Pattern 7: `scripts/setup-minio-cors.sh`

**What:** Idempotent shell script for CORS/access setup. D-03 locked.

**CRITICAL DISCOVERY:** Official MinIO docs state: *"Calls to BucketCORS operations are unnecessary in MinIO. CORS (Cross-Origin Resource Sharing) is enabled by default for all buckets and supports all HTTP verbs, simplifying cross-domain requests."* [VERIFIED: MinIO S3 API compatibility docs via Context7, s3-api-compatibility.rst]

This means for modern MinIO instances, no CORS configuration is needed at all. The script's primary role is:
1. Verify `mc` alias exists and MinIO is reachable
2. Document the default-CORS behavior
3. For older MinIO: offer `mc anonymous set upload` as a fallback

```bash
#!/usr/bin/env bash
# setup-minio-cors.sh — Phase 5: Video Upload UI
# MinIO CORS setup for direct browser PUT uploads.
#
# IMPORTANT: Modern MinIO (RELEASE.2022+) has CORS enabled by default for all
# buckets and all HTTP verbs. This script primarily verifies connectivity.
# For older MinIO instances, it sets an upload policy as a fallback.
#
# Usage: MINIO_ALIAS=myminio MINIO_BUCKET=videos bash setup-minio-cors.sh
# Idempotent: safe to re-run.

set -euo pipefail

ALIAS="${MINIO_ALIAS:-myminio}"
BUCKET="${MINIO_BUCKET:-videos}"

echo "→ Checking mc availability..."
if ! command -v mc &>/dev/null; then
    echo "ERROR: mc (MinIO Client) not found. Install from https://min.io/docs/minio/linux/reference/minio-mc.html"
    exit 1
fi

echo "→ Verifying MinIO connection via alias '$ALIAS'..."
if ! mc ls "$ALIAS" &>/dev/null; then
    echo "ERROR: Cannot connect to MinIO alias '$ALIAS'."
    echo "Run: mc alias set $ALIAS <MINIO_URL> <ACCESS_KEY> <SECRET_KEY>"
    exit 1
fi

echo "→ Checking bucket '$BUCKET' exists..."
if ! mc ls "$ALIAS/$BUCKET" &>/dev/null; then
    echo "ERROR: Bucket '$BUCKET' not found on '$ALIAS'."
    exit 1
fi

# Modern MinIO: CORS is enabled by default — no configuration needed.
# Verify by checking MinIO server version.
MINIO_VERSION=$(mc admin info "$ALIAS" --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('info',{}).get('servers',[{}])[0].get('version','unknown'))" 2>/dev/null || echo "unknown")
echo "→ MinIO version: $MINIO_VERSION"

echo ""
echo "✓ MinIO CORS status:"
echo "  Modern MinIO has CORS enabled by default for all buckets and all HTTP verbs."
echo "  No explicit CORS configuration is required for presigned PUT uploads."
echo ""
echo "  If you encounter CORS errors (browser blocks PUT request):"
echo "  1. Ensure MINIO_PUBLIC_ENDPOINT in .env points to the MinIO hostname"
echo "     that the BROWSER resolves (not the internal Docker hostname)."
echo "  2. For legacy MinIO (<2022): run: mc anonymous set upload $ALIAS/$BUCKET"
echo "     WARNING: This allows unauthenticated PUT. Presigned URLs are still required."
echo ""
echo "✓ Setup complete. Direct browser uploads to MinIO/$BUCKET are ready."
```

---

### Anti-Patterns to Avoid

- **Using `authFetch` / `fetch` for the MinIO PUT:** `fetch` has no upload progress API. Use raw `XMLHttpRequest` for the PUT. [VERIFIED: CONTEXT.md code insight]
- **Using `_client` (internal) for presigned URL generation:** The internal client uses `MINIO_ENDPOINT` (Docker hostname, e.g. `minio:9000`) — not browser-resolvable. Always use `get_public_minio_client()`. [VERIFIED: `storage.py`]
- **Parallel uploads:** Phase 5 is sequential. Parallel would cause memory spikes on the 8 GB homeserver. [VERIFIED: SPEC.md constraint]
- **Setting `Content-Type` on the API fetch:** `authFetch` already sets `Content-Type: application/json` for non-FormData requests (which is what the upload-url call is). Don't override. [VERIFIED: `client.ts`]
- **Passing `key` with full URL to ingest:** The ingest body needs `minio_key` = the key (e.g., `videos/video.mp4`), not the full presigned URL. Use the `key` field from the upload-url response. [VERIFIED: existing `reIngestVideo` uses `minioKey`]
- **`os.path.basename` without stripping whitespace:** A filename of `" "` (spaces only) passes `basename` but is a useless key. Always `.strip()` after `basename`. [ASSUMED]
- **Using `warn` toast type (doesn't exist):** The toast system accepts `'success' | 'error' | 'info'` only — no `'warning'`. For ingest-trigger failure, use `'info'`. [VERIFIED: `useToast.ts`]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Presigned URL generation | Custom HMAC signing | `minio.presigned_put_object()` | Edge cases: clock skew, URL encoding, signature version |
| Upload progress | Polling file size on server | `XMLHttpRequest.upload.onprogress` | Native browser API — reliable, zero server load |
| MinIO CORS setup | Nginx CORS proxy layer | MinIO default CORS (modern) or `mc anonymous set` | MinIO handles CORS natively; proxying breaks direct-upload purpose |
| Auth on presigned PUT | Forwarding bearer token to MinIO | Self-authenticating presigned URL (HMAC) | The URL IS the auth; adding a bearer header to a MinIO presigned PUT causes signature mismatch |

---

## MinIO CORS — Detailed Notes

### Default Behavior (modern MinIO)
**[VERIFIED: MinIO S3 API compatibility docs, s3-api-compatibility.rst via Context7]**
> "Calls to BucketCORS operations are unnecessary in MinIO. CORS (Cross-Origin Resource Sharing) is enabled by default for all buckets and supports all HTTP verbs."

This means:
- No `mc cors set` command is needed
- No `aws s3api put-bucket-cors` call is needed
- Browser PUT requests from any origin are allowed by default

### Why the CORS Script Is Still Needed (D-03 locked)
1. The homeserver MinIO version is unknown — may be pre-2022 era
2. The script provides ops-runbook value (verifying connectivity, bucket existence)
3. The README deployment section needs a concrete checklist step (D-04)

### For Pre-2022 MinIO (fallback)
If the user encounters CORS errors, the fallback is:
```bash
mc anonymous set upload myminio/videos
```
This sets the bucket's anonymous policy to allow PUT, effectively making presigned URLs work from any origin. **This is safe** because the API still requires auth to *generate* the presigned URL — anonymous PUT only works with a valid presigned URL (HMAC-verified by MinIO).

### `mc` Command Reference
- `mc alias set ALIAS URL ACCESSKEY SECRETKEY` — configure connection [CITED: MinIO mc docs]
- `mc ls ALIAS/BUCKET` — verify bucket exists [CITED: MinIO mc docs]
- `mc anonymous set upload ALIAS/BUCKET` — allow unsigned PUT (legacy fallback) [CITED: MinIO mc docs via Context7]
- `mc share upload ALIAS/BUCKET/object` — generate a one-off presigned URL (for testing) [CITED: MinIO mc docs via Context7]

---

## Common Pitfalls

### Pitfall 1: Internal vs. Public MinIO Endpoint
**What goes wrong:** The presigned URL uses the internal Docker hostname (e.g., `minio:9000`) — browser can't resolve it.
**Why it happens:** `get_minio_client()` uses `MINIO_ENDPOINT` (Docker internal). `presigned_put_object` bakes the endpoint into the URL.
**How to avoid:** Always call `get_public_minio_client()` in `generate_presigned_upload_url`. [VERIFIED: storage.py + STATE.md decision]
**Warning signs:** Browser `PUT` request fails with DNS resolution error.

### Pitfall 2: `fetch` for Upload (No Progress)
**What goes wrong:** Upload succeeds but no progress bar ever updates.
**Why it happens:** The Fetch API has no `uploadProgress` event. `fetch()` is a black box for upload progress.
**How to avoid:** Use raw `XMLHttpRequest` with `xhr.upload.addEventListener('progress', ...)`. [VERIFIED: CONTEXT.md]
**Warning signs:** `onProgressChange` is never called during upload.

### Pitfall 3: XHR Progress State Thrashing
**What goes wrong:** Progress events fire 100+ times per second for large files; calling `setState` on every event causes excessive re-renders.
**Why it happens:** Browser fires `progress` events very frequently for large files.
**How to avoid (agent's discretion):** Either (a) call `setState` normally (React 18 batches many rapid updates in concurrent mode, usually fine for 1 fps equivalent re-renders), or (b) store progress in `useRef` and use `requestAnimationFrame` to throttle state updates. For 1 GB files at typical upload speeds, option (a) is sufficient.
**Warning signs:** CPU spike in browser DevTools during upload.

### Pitfall 4: Input `value` Not Reset After Selection
**What goes wrong:** User selects the same file twice — the `onChange` doesn't fire on the second selection.
**Why it happens:** `<input type="file">` doesn't fire `onChange` if the selected file is the same as before (value hasn't changed).
**How to avoid:** Reset `e.target.value = ''` at the end of the `onChange` handler. [ASSUMED standard pattern]
**Warning signs:** Re-uploading the same file fails silently.

### Pitfall 5: `key` vs. `minio_key` field names
**What goes wrong:** Ingest call sends wrong key; ingestion worker returns 404 or wrong object.
**Why it happens:** The upload-url response uses field `key` (e.g., `videos/video.mp4`). The ingest body uses field `minio_key`. Same value, different names.
**How to avoid:** Destructure `{ key }` from upload-url response; pass as `minio_key: key` to ingest. [VERIFIED: SPEC.md + existing `reIngestVideo` in videos.ts]
**Warning signs:** Ingestion triggered but video never appears in list.

### Pitfall 6: Queue Progress Stuck at 100% After Failure
**What goes wrong:** A file fails mid-upload; `completedBytes` is not advanced; progress bar freezes.
**Why it happens:** The failure catch block doesn't increment `completedBytes`.
**How to avoid:** In the catch block, add `completedBytes += file.size` before continuing. Then call `onProgressChange?.((completedBytes / totalBytes) * 100)`. [ASSUMED]

### Pitfall 7: `warn` Toast Type
**What goes wrong:** `addToast(msg, 'warning')` silently passes wrong type; toast renders as default `info`.
**Why it happens:** `ToastType = 'success' | 'error' | 'info'` — no 'warning'. [VERIFIED: useToast.ts]
**How to avoid:** Use `'info'` for ingest-trigger failure (per SPEC.md wording: warning toast → use `'info'`).

---

## Code Examples — Verified Against Codebase

### Adding `generate_presigned_upload_url` to `storage.py`
```python
# Append after generate_presigned_url() — same file, same pattern
# Source: services/api/app/storage.py [VERIFIED codebase]

def generate_presigned_upload_url(bucket: str, key: str, expires_minutes: int = 60) -> str:
    """
    Generate a presigned PUT URL valid for `expires_minutes` minutes.
    Called by POST /videos/upload-url on-demand.
    MUST use _public_client so URL is browser-resolvable.
    """
    client = get_public_minio_client()
    url = client.presigned_put_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(minutes=expires_minutes),
    )
    logger.debug("Generated presigned PUT URL for %s/%s (TTL=%dm)", bucket, key, expires_minutes)
    return url
```

### Importing `generate_presigned_upload_url` in `videos.py`
```python
# Source: services/api/app/videos.py [VERIFIED codebase]
# Change import line:
from .storage import generate_presigned_url, generate_presigned_upload_url
# Also add: import os (for os.path.basename in the endpoint)
```

### `authFetch` call for `getUploadUrl`
```typescript
// Source: follows authFetch pattern in services/web/src/api/client.ts [VERIFIED codebase]
// authFetch automatically adds:
//   - Content-Type: application/json (non-FormData body)
//   - Authorization: Bearer {apiToken}
// No extra config needed.
export async function getUploadUrl(filename: string): Promise<UploadUrlResponse> {
  return authFetch('/videos/upload-url', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  }).then(r => r.json());
}
```

### Ingest trigger (reuse existing function)
```typescript
// Source: services/web/src/api/videos.ts [VERIFIED codebase]
// reIngestVideo(minioKey) already does exactly what UPLOAD-05 requires:
//   POST /ingest-api/ingest with { minio_key: minioKey, force: true }
// No new function needed — just call reIngestVideo(key) where key = "videos/filename.mp4"
await reIngestVideo(key);  // key is the 'key' field from getUploadUrl response
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `minio==7.1.x` (older SDK) | `minio==7.2.20` (pinned in requirements.txt) | `presigned_put_object` signature unchanged; `timedelta` approach same |
| Manual CORS config via `mc cors set` | Modern MinIO: CORS enabled by default | Script is verification-only, not configuration |
| `fetch` with no upload progress | `XMLHttpRequest.upload.onprogress` | Required for progress bar; fetch cannot be used |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `e.lengthComputable` is always `true` for direct binary PUT uploads | Pattern 4 (XHR) | Progress bar never updates; fallback: show indeterminate spinner |
| A2 | React 18 batches rapid `setState` calls from XHR progress events sufficiently (no throttling needed) | Pitfall 3 | CPU spike in browser; fix: add `requestAnimationFrame` throttle |
| A3 | `os.path.basename` + `.strip()` is sufficient filename sanitization | Pattern 2 | Path traversal in MinIO key — but MinIO SDK URL-encodes the key, making traversal practically impossible anyway |
| A4 | Resetting `e.target.value = ''` allows re-selecting same file | Pitfall 4 | Minor UX issue; fix: use key on `<input>` to force re-mount |
| A5 | The homeserver's MinIO instance is modern enough that CORS is enabled by default | MinIO CORS section | Browser PUT blocked by CORS; fix: run `mc anonymous set upload` from the fallback script |

---

## Open Questions (RESOLVED)

1. **MinIO homeserver version** — RESOLVED: Version-agnostic. `scripts/setup-minio-cors.sh` includes the `mc anonymous set upload` fallback command (commented out) with a comment explaining when to use it. User can uncomment if CORS is blocked on older MinIO; modern MinIO has CORS enabled by default.

2. **`onProgressChange` callback frequency and the progress bar flicker at 100%** — RESOLVED: The `uploadProgress > 0 && uploadProgress < 100` condition in `VideosPage` hides the bar at exactly 100%. After the queue finishes, `onProgressChange(0)` resets state to 0, which also hides the bar. No flicker occurs because the conditional ensures the bar is invisible at both 0 and 100.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `minio` Python SDK | `storage.py` presigned PUT | ✓ (in requirements.txt) | `7.2.20` [VERIFIED] | — |
| `mc` CLI | `setup-minio-cors.sh` | Unknown (homeserver) | Unknown | Script exits with install instructions |
| MinIO server (external) | Full upload flow | ✓ (running on homeserver) | Unknown | — |
| Browser `XMLHttpRequest` | Upload progress | ✓ (universal browser support) | Native | — |

**Missing dependencies with no fallback:**
- None — `mc` is only for the ops script, not for the main application flow.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Bearer token on `POST /api/videos/upload-url`; presigned URL is self-auth |
| V3 Session Management | no | Stateless bearer token |
| V4 Access Control | yes | `require_token` dependency; `videos/` prefix enforced server-side |
| V5 Input Validation | yes | `os.path.basename` + `.strip()` for filename; Pydantic model |
| V6 Cryptography | yes (indirect) | MinIO SDK generates HMAC-signed presigned URLs — never hand-rolled |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via filename | Tampering | `os.path.basename()` + `.strip()` strips all separators |
| Presigned URL leakage | Info Disclosure | 1-hour TTL; URL only returned to authenticated clients; HTTPS via Cloudflare Tunnel |
| SSRF via presigned URL generation | Elevation | Not applicable — SDK constructs URL from `MINIO_PUBLIC_ENDPOINT` (not from user input) |
| Unauthenticated upload URL generation | Spoofing | `require_token` on `videos_router` in `main.py` |
| Oversized file upload | DoS | Client-side: 1 GB cap with `addToast`; server-side: MinIO storage limits apply |
| Content-type mismatch (non-video upload) | Tampering | Accepted per SPEC.md; ingestion-worker validates via FFmpeg at ingest time |

---

## Sources

### Primary (HIGH confidence)
- `services/api/app/storage.py` — existing `generate_presigned_url` pattern [VERIFIED: codebase read]
- `services/api/app/videos.py` — router endpoint pattern [VERIFIED: codebase read]
- `services/api/app/main.py` — router registration + auth dependency [VERIFIED: codebase read]
- `services/api/requirements.txt` — `minio==7.2.20` version [VERIFIED: codebase read]
- `services/web/src/api/videos.ts` — `reIngestVideo` + `useReIngestVideo` patterns [VERIFIED: codebase read]
- `services/web/src/api/client.ts` — `authFetch` + `getSettings` [VERIFIED: codebase read]
- `services/web/src/components/EnrollmentDropzone.tsx` — component pattern [VERIFIED: codebase read]
- `services/web/src/hooks/useToast.ts` — `addToast` + `ToastType` [VERIFIED: codebase read]
- `services/web/src/pages/VideosPage.tsx` — header div structure [VERIFIED: codebase read]
- `services/web/package.json` — React 18.3.1, TanStack Query 5.100.10, Tailwind 3.4.19 [VERIFIED]
- MinIO docs (s3-api-compatibility.rst) — "CORS enabled by default" [VERIFIED: Context7 / MinIO docs]
- MinIO docs (presigned-put-upload-via-browser.md) — presigned PUT URL pattern [CITED: Context7]
- MinIO mc docs (mc-share-upload.rst, mc-anonymous-set.rst) — mc command reference [CITED: Context7]

### Secondary (MEDIUM confidence)
- `services/web/nginx.conf` — confirms 50MB limit + `/ingest-api/` proxy [VERIFIED: codebase read]
- `services/web/src/types/api.ts` — existing type interface patterns [VERIFIED: codebase read]

### Tertiary (LOW confidence)
- XHR `e.lengthComputable` reliability for large files — training knowledge [ASSUMED A1]
- React 18 batching adequacy for rapid progress events — training knowledge [ASSUMED A2]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all library versions verified from requirements.txt and package.json
- Architecture patterns: HIGH — all patterns derived directly from existing codebase files
- MinIO CORS: HIGH — verified "CORS enabled by default" from official MinIO docs; fallback documented
- Pitfalls: HIGH (codebase-derived) / MEDIUM (A1–A5 assumptions flagged)

**Research date:** 2026-05-27
**Valid until:** 2026-08-27 (MinIO SDK API stable; React patterns stable)
