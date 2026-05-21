# Phase 5: Video Upload — Pattern Map

**Mapped:** 2026-05-27
**Files analyzed:** 6 (2 new, 4 modified)
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/api/app/storage.py` | utility | request-response | `services/api/app/storage.py` (existing `generate_presigned_url`) | exact — same file, mirror function |
| `services/api/app/videos.py` | controller/route | request-response | `services/api/app/videos.py` (existing `stream_video_url`) | exact — same file, same router |
| `services/web/src/components/VideoUploadButton.tsx` | component | file-I/O + event-driven | `services/web/src/components/EnrollmentDropzone.tsx` | exact — same role (upload component, file picker, `addToast`, queue state) |
| `services/web/src/api/videos.ts` | service / hook | request-response | `services/web/src/api/videos.ts` (existing `useReIngestVideo`, `reIngestVideo`) | exact — same file, same hook pattern |
| `services/web/src/pages/VideosPage.tsx` | component/page | request-response | `services/web/src/pages/VideosPage.tsx` (existing header div) | exact — same file, same header structure |
| `scripts/setup-minio-cors.sh` | config/ops script | — | `scripts/enroll_face.py` (only existing script; different language) | no analog — shell script is novel |

---

## Pattern Assignments

### 1. `services/api/app/storage.py` — ADD `generate_presigned_upload_url()`

**Analog:** `services/api/app/storage.py` — `generate_presigned_url()` function (lines 54–66)

**Imports pattern** (lines 1–19 — already present, no new imports needed):
```python
import logging
from datetime import timedelta
from typing import Optional

from minio import Minio

from . import config

logger = logging.getLogger(__name__)
```

**Core pattern to mirror** (lines 54–66 — exact mirror, substitute `presigned_put_object` for `presigned_get_object` and `expires_minutes` for `expires_hours`):
```python
def generate_presigned_url(bucket: str, key: str, expires_hours: int = 1) -> str:
    """
    Generate a presigned GET URL valid for `expires_hours` hours.
    Called per-request at redirect time — never called during search queries.
    """
    client = get_public_minio_client()
    url = client.presigned_get_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(hours=expires_hours),
    )
    logger.debug("Generated presigned URL for %s/%s (TTL=%dh)", bucket, key, expires_hours)
    return url
```

**New function to add** (place immediately after `generate_presigned_url`, same file):
```python
def generate_presigned_upload_url(bucket: str, key: str, expires_minutes: int = 60) -> str:
    """
    Generate a presigned PUT URL valid for expires_minutes minutes.
    MUST use get_public_minio_client() so the URL is browser-resolvable
    (uses MINIO_PUBLIC_ENDPOINT, not internal MINIO_ENDPOINT).
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

**Critical constraint:** MUST call `get_public_minio_client()` — not `get_minio_client()`. The `_public_client` uses `MINIO_PUBLIC_ENDPOINT` so the returned URL is browser-resolvable (same constraint already documented in the existing `generate_presigned_url`).

---

### 2. `services/api/app/videos.py` — ADD `POST /videos/upload-url` endpoint

**Analog:** `services/api/app/videos.py` — `stream_video_url()` endpoint (lines 89–108) — same router, same Pydantic response model pattern.

**Imports to extend** (lines 1–19 — add `generate_presigned_upload_url` to the existing import):
```python
from .storage import generate_presigned_url, generate_presigned_upload_url
```

**Existing Pydantic model pattern** (lines 26–46 — copy this structure for new models):
```python
class VideoListItem(BaseModel):
    id:               str
    minio_key:        str
    ...

class StreamUrlResponse(BaseModel):
    url: str
```

**New Pydantic models to add** (insert after existing model definitions, before first `@router` decorator):
```python
class UploadUrlRequest(BaseModel):
    filename: str          # original filename from browser; sanitized server-side

class UploadUrlResponse(BaseModel):
    url: str               # presigned PUT URL — browser PUTs directly here
    key: str               # minio_key to use in POST /ingest-api/ingest
```

**Existing endpoint pattern to mirror** (lines 89–108):
```python
@router.get("/{video_id}/stream-url", response_model=StreamUrlResponse)
async def stream_video_url(video_id: UUID) -> StreamUrlResponse:
    ...
    url = generate_presigned_url(
        bucket=config.MINIO_BUCKET_VIDEOS,
        key=row["minio_key"],
        expires_hours=1,
    )
    return StreamUrlResponse(url=url)
```

**New endpoint to add** (place after the last `@router` endpoint):
```python
@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(body: UploadUrlRequest) -> UploadUrlResponse:
    """
    Returns a presigned MinIO PUT URL for direct browser → MinIO upload.
    The client PUTs the video bytes directly to this URL (no nginx proxy),
    then calls POST /ingest-api/ingest with the returned key.
    TTL: 60 minutes.
    """
    import os, re
    # Sanitize: strip directory traversal, keep alphanumeric/dash/underscore/dot
    safe_name = re.sub(r"[^\w\-.]", "_", os.path.basename(body.filename))
    key = f"videos/{safe_name}"
    url = generate_presigned_upload_url(
        bucket=config.MINIO_BUCKET_VIDEOS,
        key=key,
        expires_minutes=60,
    )
    return UploadUrlResponse(url=url, key=key)
```

**Auth:** No change needed. `videos_router` is already registered in `main.py` with `dependencies=[Depends(require_token)]` (line 62). The new endpoint inherits this automatically.

**Router registration reference** (`services/api/app/main.py` line 62):
```python
app.include_router(videos_router,  dependencies=[Depends(require_token)])
```

---

### 3. `services/web/src/components/VideoUploadButton.tsx` — NEW component

**Analog:** `services/web/src/components/EnrollmentDropzone.tsx` (entire file, 173 lines)

**Imports pattern** (lines 1–4 of EnrollmentDropzone — copy structure, replace `useEnrollPerson` with `useUploadVideo`):
```typescript
import { useState, useRef } from 'react';
import clsx from 'clsx';
import { useEnrollPerson } from '../api/persons';
import { addToast } from '../hooks/useToast';
```

**New component imports** (adapt from analog):
```typescript
import { useState, useRef } from 'react';
import clsx from 'clsx';
import { getUploadUrl, useUploadVideo } from '../api/videos';
import { addToast } from '../hooks/useToast';
import { getSettings } from '../api/client';
```

**State pattern** (lines 17–23 of EnrollmentDropzone — copy self-contained state structure):
```typescript
const [files,     setFiles]     = useState<File[]>([]);
const [dragOver,  setDragOver]  = useState(false);
const [rejected,  setRejected]  = useState<RejectedFile[]>([]);
const [warning,   setWarning]   = useState<string | null>(null);
const [previews,  setPreviews]  = useState<string[]>([]);
const fileInputRef = useRef<HTMLInputElement>(null);
```

**New component state** (adapt from analog, add upload-specific state):
```typescript
// Upload queue state
const [isUploading,    setIsUploading]    = useState(false);
const [progress,       setProgress]       = useState(0);   // 0-100, overall queue
const [uploadedCount,  setUploadedCount]  = useState<number | null>(null); // N in "N/total uploaded"
const [totalCount,     setTotalCount]     = useState(0);
const fileInputRef = useRef<HTMLInputElement>(null);
const xhrRef       = useRef<XMLHttpRequest | null>(null);  // current in-flight XHR
```

**File input pattern** (lines 97–104 of EnrollmentDropzone — exact copy, change `accept`):
```tsx
<input
  ref={fileInputRef}
  type="file"
  multiple
  accept="image/*"       // ← change to "video/*"
  className="hidden"
  onChange={e => addFiles(Array.from(e.target.files ?? []))}
/>
```

**Toast call pattern** (lines 69–72 of EnrollmentDropzone — exact pattern to copy):
```typescript
addToast(
  `${result.enrolled} photo${result.enrolled !== 1 ? 's' : ''} enrolled successfully`,
  'success'
);
```

**Button disabled/text pattern** (lines 161–169 of EnrollmentDropzone — copy structure):
```tsx
<button
  onClick={handleSubmit}
  disabled={enroll.isPending || files.length === 0}
  className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
>
  {enroll.isPending
    ? 'Uploading…'
    : `Upload ${files.length} image${files.length !== 1 ? 's' : ''}`}
</button>
```

**New button text logic** (adapt from analog per D-10):
```typescript
// Button text per D-10:
// - Normal:   "Upload Video"
// - Uploading: "Uploading…"  (static, no %)
// - Done:     "{N}/{total} uploaded"
const buttonLabel =
  isUploading ? 'Uploading…' :
  uploadedCount !== null ? `${uploadedCount}/${totalCount} uploaded` :
  'Upload Video';
```

**XHR upload-progress pattern** (no direct analog in codebase — use Web API):
```typescript
// Raw XHR required — fetch has no native upload progress event
function uploadFileXHR(url: string, file: File, onProgress: (pct: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;
    xhr.open('PUT', url);
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) onProgress((e.loaded / e.total) * 100);
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`PUT failed: ${xhr.status}`));
    });
    xhr.addEventListener('error', () => reject(new Error('Network error during upload')));
    xhr.send(file);
  });
}
```

**Auto-ingest trigger pattern** (copy verbatim from `reIngestVideo` in `services/web/src/api/videos.ts` lines 14–27):
```typescript
const { apiToken } = getSettings();
const response = await fetch('/ingest-api/ingest', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
  },
  body: JSON.stringify({ minio_key: minioKey, force: true }),
});
if (!response.ok) {
  const text = await response.text().catch(() => response.statusText);
  throw new Error(`${response.status}: ${text}`);
}
```

**Client-side validation** (new, no direct analog — follow SPEC.md rules):
```typescript
const MAX_SIZE = 1_073_741_824; // 1 GB
function validateFiles(incoming: File[]): { valid: File[]; invalid: Array<{name: string; reason: string}> } {
  const valid: File[] = [];
  const invalid: Array<{name: string; reason: string}> = [];
  for (const f of incoming) {
    if (f.size === 0)            invalid.push({ name: f.name, reason: 'File is empty' });
    else if (f.size > MAX_SIZE)  invalid.push({ name: f.name, reason: 'File exceeds 1 GB limit' });
    else                         valid.push(f);
  }
  return { valid, invalid };
}
```

**Props interface** (follow EnrollmentDropzone `Props` pattern, lines 11–14):
```typescript
interface Props {
  onUploadComplete?: (succeeded: number, total: number) => void;
  // progress is managed internally; bar rendered inside this component OR exposed via prop
}
```

**Progress bar** (agent's discretion per CONTEXT.md — recommended pattern):
```tsx
{/* Thin progress bar between header and table — only visible during upload (D-09) */}
{isUploading && progress > 0 && (
  <div className="h-1 w-full bg-gray-200 rounded-full overflow-hidden">
    <div
      className="h-1 bg-blue-500 transition-all duration-300"
      style={{ width: `${progress}%` }}
    />
  </div>
)}
```

---

### 4. `services/web/src/api/videos.ts` — ADD `getUploadUrl()` + `useUploadVideo()`

**Analog:** `services/web/src/api/videos.ts` — entire file (47 lines); specifically `reIngestVideo` (lines 14–27) and `useReIngestVideo` (lines 40–46).

**Existing imports** (lines 1–3 — no changes needed; `authFetch`, `getSettings`, `useQueryClient` all already imported):
```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { VideoListResponse, StreamUrlResponse } from '../types/api';
```

**Extended imports** (add the new response type):
```typescript
import type { VideoListResponse, StreamUrlResponse, UploadUrlResponse } from '../types/api';
```

**Existing plain function pattern** (lines 14–27 — copy structure for `getUploadUrl`):
```typescript
export async function reIngestVideo(minioKey: string): Promise<void> {
  const { apiToken } = getSettings();
  const response = await fetch('/ingest-api/ingest', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
    },
    body: JSON.stringify({ minio_key: minioKey, force: true }),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }
}
```

**New `getUploadUrl` function** (uses `authFetch` — contrast with `reIngestVideo` which uses raw `fetch`):
```typescript
export async function getUploadUrl(filename: string): Promise<UploadUrlResponse> {
  return authFetch('/videos/upload-url', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  }).then(r => r.json());
}
```

**Existing hook pattern** (lines 40–46 — copy structure for `useUploadVideo`):
```typescript
export function useReIngestVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (minioKey: string) => reIngestVideo(minioKey),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['videos'] }),
  });
}
```

**Note on `useUploadVideo`:** The XHR progress tracking means this hook is *lighter* than `useReIngestVideo` — the component controls the upload loop and XHR internally. The hook only wraps the ingest trigger + query invalidation, OR the entire upload operation can be self-contained in the component (agent's discretion). Recommended minimal hook:
```typescript
export function useUploadVideo() {
  const qc = useQueryClient();
  // Exposes only the ingest trigger + invalidation; XHR loop lives in the component
  return {
    triggerIngest: async (minioKey: string) => {
      await reIngestVideo(minioKey);
      await qc.invalidateQueries({ queryKey: ['videos'] });
    },
  };
}
```

**Query invalidation pattern** (line 44 — copy verbatim):
```typescript
qc.invalidateQueries({ queryKey: ['videos'] })
```

---

### 5. `services/web/src/pages/VideosPage.tsx` — ADD button + progress bar

**Analog:** `services/web/src/pages/VideosPage.tsx` — existing file (169 lines)

**Existing header div** (lines 50–55 — this is the insertion point for the button):
```tsx
<div className="flex items-center justify-between mb-5">
  <h1 className="text-lg font-semibold text-gray-900">Videos</h1>
  {data && (
    <span className="text-sm text-gray-500">{data.total} video{data.total !== 1 ? 's' : ''}</span>
  )}
</div>
```

**New header div** (add `VideoUploadButton` to the right side, alongside the video count span):
```tsx
<div className="flex items-center justify-between mb-5">
  <h1 className="text-lg font-semibold text-gray-900">Videos</h1>
  <div className="flex items-center gap-3">
    {data && (
      <span className="text-sm text-gray-500">{data.total} video{data.total !== 1 ? 's' : ''}</span>
    )}
    <VideoUploadButton />
  </div>
</div>
```

**Progress bar insertion point** (between line 55 `</div>` and line 57 `{/* Loading */}`):
```tsx
</div>  {/* end header row */}

{/* Progress bar — only visible during upload (D-07, D-09) */}
{uploadProgress > 0 && uploadProgress < 100 && (
  <div className="h-1 w-full bg-gray-200 rounded-full overflow-hidden mb-4">
    <div
      className="h-1 bg-blue-500 transition-all duration-300"
      style={{ width: `${uploadProgress}%` }}
    />
  </div>
)}

{/* Loading */}
```

**Existing imports** (lines 1–6 — add `VideoUploadButton`):
```typescript
import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import { useVideos, useReIngestVideo } from '../api/videos';
import { useSettings } from '../context/SettingsContext';
import StatusBadge from '../components/StatusBadge';
```

**Extended imports:**
```typescript
import VideoUploadButton from '../components/VideoUploadButton';
```

**Note on progress state:** If the progress bar is controlled by `VideosPage` (lifted state), add `const [uploadProgress, setUploadProgress] = useState(0)` to `VideosPage` state and pass `onProgress={setUploadProgress}` as a prop to `VideoUploadButton`. Alternatively, manage it fully inside `VideoUploadButton` (agent's discretion per CONTEXT.md).

---

### 6. `scripts/setup-minio-cors.sh` — NEW ops script

**Analog:** None with close role match. Only existing script is `scripts/enroll_face.py` (Python, different purpose). Use `scripts/enroll_face.py` only for header comment style.

**Header comment style** (from `scripts/enroll_face.py` — project convention):
```python
#!/usr/bin/env python3
"""
Enroll a face from a local image into HomeVideoSearcher.
...
"""
```

**Shell script equivalent convention:**
```bash
#!/usr/bin/env bash
# setup-minio-cors.sh — Configure MinIO CORS for VideoUpload (Phase 5)
# ...
```

**Recommended script structure** (no codebase analog — derive from research):
```bash
#!/usr/bin/env bash
# setup-minio-cors.sh — Configure MinIO CORS for VideoUpload (Phase 5)
#
# USAGE:  ./scripts/setup-minio-cors.sh [MINIO_ALIAS] [BUCKET]
#
# Idempotent — safe to re-run (D-04).
#
# MinIO CORS note (from research): MinIO enables CORS for all buckets
# by default in recent versions. This script verifies connectivity and
# falls back to explicit mc commands for older MinIO versions.
set -euo pipefail

ALIAS="${1:-myminio}"
BUCKET="${2:-videos}"
ORIGINS=("http://homevideosearcher.shumov.eu" "http://localhost:5173" "http://localhost:3000")

# 1. Verify mc is installed
command -v mc >/dev/null 2>&1 || { echo "ERROR: mc (MinIO Client) not found. Install from https://min.io/docs/minio/linux/reference/minio-mc.html"; exit 1; }

# 2. Verify alias connectivity
mc alias ls "$ALIAS" >/dev/null 2>&1 || { echo "ERROR: MinIO alias '$ALIAS' not configured. Run: mc alias set $ALIAS <endpoint> <access_key> <secret_key>"; exit 1; }

# 3. Set anonymous upload policy (idempotent)
echo "Setting bucket policy for $ALIAS/$BUCKET ..."
mc anonymous set upload "$ALIAS/$BUCKET"

echo "Done. CORS should be active for bucket '$BUCKET'."
```

---

## Shared Patterns

### Authentication (API side)
**Source:** `services/api/app/main.py` lines 55–63
**Apply to:** New `POST /videos/upload-url` endpoint (inherits automatically via router registration)
```python
# Router is already registered with token requirement — new endpoint inherits it:
app.include_router(videos_router,  dependencies=[Depends(require_token)])
```

### Authentication (Client side — API calls)
**Source:** `services/web/src/api/client.ts` lines 16–37
**Apply to:** `getUploadUrl()` in `videos.ts` (use `authFetch`). NOT for the MinIO PUT — that uses the presigned URL directly.
```typescript
export async function authFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const { apiBaseUrl, apiToken } = getSettings();
  const prefix = apiBaseUrl || '/api';
  const headers: HeadersInit = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
    ...(options.headers ?? {}),
  };
  const response = await fetch(`${prefix}${path}`, { ...options, headers });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }
  return response;
}
```

### Authentication (Ingest trigger — raw fetch pattern)
**Source:** `services/web/src/api/videos.ts` lines 14–27
**Apply to:** Ingest trigger call in `VideoUploadButton` or `useUploadVideo`
```typescript
const { apiToken } = getSettings();
const response = await fetch('/ingest-api/ingest', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
  },
  body: JSON.stringify({ minio_key: minioKey, force: true }),
});
```

### Toast Notifications
**Source:** `services/web/src/hooks/useToast.ts` lines 20–28 + `services/web/src/components/EnrollmentDropzone.tsx` lines 69–72
**Apply to:** `VideoUploadButton.tsx` for all outcomes (success, upload-failed, ingest-failed, validation-rejected)
```typescript
// Call from anywhere — no hook required (module-level singleton)
addToast('message text', 'success');  // or 'error' or 'info'
```

### Query Invalidation
**Source:** `services/web/src/api/videos.ts` line 44
**Apply to:** After ingest trigger succeeds in the upload flow
```typescript
qc.invalidateQueries({ queryKey: ['videos'] })
```

### MinIO Presigned URL — `_public_client` constraint
**Source:** `services/api/app/storage.py` lines 37–51 + lines 54–66
**Apply to:** `generate_presigned_upload_url()` in `storage.py`
```python
# MUST use get_public_minio_client() — not get_minio_client()
# This uses MINIO_PUBLIC_ENDPOINT so the URL is browser-resolvable
client = get_public_minio_client()
url = client.presigned_put_object(bucket_name=bucket, object_name=key, expires=timedelta(minutes=expires_minutes))
```

---

## Types to Add

`services/web/src/types/api.ts` — add these interfaces (no existing analog in the file; follow existing `VideoListResponse` / `StreamUrlResponse` structure):

```typescript
export interface UploadUrlRequest {
  filename: string;
}

export interface UploadUrlResponse {
  url: string;   // presigned PUT URL
  key: string;   // minio_key for ingest trigger
}
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `scripts/setup-minio-cors.sh` | ops / config script | — | Only existing script is Python (`enroll_face.py`); shell scripts are novel in this codebase |

---

## Metadata

**Analog search scope:** `services/api/app/`, `services/web/src/api/`, `services/web/src/components/`, `services/web/src/pages/`, `services/web/src/hooks/`, `scripts/`
**Files read:** `storage.py`, `videos.py`, `main.py`, `config.py`, `EnrollmentDropzone.tsx`, `videos.ts` (api), `VideosPage.tsx`, `client.ts`, `useToast.ts`
**Pattern extraction date:** 2026-05-27
