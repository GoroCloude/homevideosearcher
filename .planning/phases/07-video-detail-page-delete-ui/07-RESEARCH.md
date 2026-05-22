# Phase 7: Video Detail Page + Delete UI — Research

**Researched:** 2025-07-22
**Domain:** React 18 + TypeScript + TanStack Query v5 + React Router v6 + Tailwind CSS v3 + Headless UI v2
**Confidence:** HIGH — all findings are VERIFIED directly from codebase source files.

---

## Summary

Phase 7 adds a `VideoDetailPage` React component and extends `VideosPage` with delete and row-click navigation. All foundational infrastructure (authFetch, TanStack Query hooks, routing, FrameThumbnail, Toast, StatusBadge, Headless UI Dialog) is already in place and proven. The work is predominantly additive: one new page, new API hooks, new type definitions, and targeted edits to two existing files (`VideosPage.tsx`, `App.tsx`).

The most novel pieces are: (1) a native `<video>` element for in-page playback (current approach opens a new tab), (2) a tab bar component (nothing like it exists yet), and (3) a seekable timeline bar — all three are straightforward to build with the existing tech stack and no new dependencies. The `FrameThumbnail` component is directly reusable for both detection and face thumbnail grids once the `frame_id` field from the API responses is used.

The delete confirmation pattern has two established precedents: the inline "Sure?" toggle pattern (`PersonCard.tsx`) and the `@headlessui/react` Dialog modal (`VideoModal.tsx`). A Headless UI Dialog is recommended for destructive delete actions to reduce mis-click risk.

**Primary recommendation:** Build `VideoDetailPage` as a self-contained page component using the `useVideoDetail`, `useVideoDetections`, `useVideoFaces`, and `useDeleteVideo` hooks. Tabs = `useState`-driven local state. Timeline = horizontal `<div>` with absolutely-positioned markers. Video = native `<video ref={videoRef}>` element. Extend `VideosPage` rows with `useNavigate` click handler and inline delete confirmation button.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Route `/videos/:id` | Frontend (React Router) | — | Client-side navigation; no SSR |
| Fetch video detail metadata | Frontend (TanStack Query) | API (GET /videos/{id}) | Cache-able fetch via authFetch |
| Fetch detections list | Frontend (TanStack Query) | API (GET /videos/{id}/detections) | Paginated or full list via authFetch |
| Fetch faces list | Frontend (TanStack Query) | API (GET /videos/{id}/faces) | Full list via authFetch |
| DELETE video | Frontend (useMutation) | API (DELETE /videos/{id}) | 204 No Content; invalidate caches |
| Video playback + seeking | Browser (`<video>` element) | — | Native HTML5 video with `currentTime` |
| Timeline seek marks | Browser (DOM + React ref) | — | `videoRef.current.currentTime = ts` |
| Row-click navigation | Frontend (useNavigate) | — | `navigate('/videos/${id}')` |
| Delete confirmation dialog | Frontend (Headless UI Dialog) | — | Already installed; used in VideoModal |
| Cache invalidation after delete | Frontend (TanStack Query) | — | `qc.invalidateQueries` across keys |

---

## Standard Stack

### Core (already installed — no new installs needed)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `react` | 18.3.1 | Component framework | [VERIFIED: package.json] |
| `react-router-dom` | 6.30.1 | `useNavigate`, `useParams` | [VERIFIED: package.json] |
| `@tanstack/react-query` | 5.100.10 | `useQuery`, `useMutation`, `useQueryClient` | [VERIFIED: package.json] |
| `@headlessui/react` | 2.2.4 | `Dialog`, `DialogPanel`, `DialogTitle` | [VERIFIED: package.json] |
| `tailwindcss` | 3.4.19 (pinned) | Utility CSS | [VERIFIED: package.json] |
| `clsx` | 2.1.1 | Conditional class names | [VERIFIED: package.json] |
| `date-fns` | 4.1.0 | `format`, `parseISO` | [VERIFIED: package.json] |

**No new dependencies required.** All libraries needed for this phase are already installed.

---

## Architecture Patterns

### System Architecture Diagram

```
VideosPage (existing)
├── Row <tr onClick>  → useNavigate('/videos/:id')
└── Delete btn        → inline confirm → useDeleteVideo.mutateAsync(id)
                                          └── DELETE /videos/{id}
                                          └── qc.invalidateQueries(['videos'])
                                          └── qc.invalidateQueries(['search', ...])

App.tsx router
└── Route path="videos/:id" → VideoDetailPage

VideoDetailPage
├── useParams({ id })
├── useVideoDetail(id)    → GET /videos/{id}       → VideoDetailItem
├── useVideoDetections(id)→ GET /videos/{id}/detections → VideoDetectionItem[]
├── useVideoFaces(id)     → GET /videos/{id}/faces  → VideoFaceItem[]
├── useDeleteVideo()      → DELETE /videos/{id}
│
├── <video ref={videoRef} src={stream_url} controls />
│
├── Tab bar  [Detections | Faces]  — useState<'detections'|'faces'>
│
├── Detections tab
│   └── grid → FrameThumbnail(frame_id) + label + confidence + timestamp
│
├── Faces tab
│   ├── grid → FrameThumbnail(frame_id) + person_name or "Unknown Cluster #N" + timestamp
│   └── TimelineBar
│       ├── marks at (ts_ms / duration_sec*1000) * 100% left
│       └── onClick → videoRef.current.currentTime = ts_ms / 1000
│
└── Delete btn → Headless UI Dialog confirm → navigate('/videos', {replace: true})
```

### Recommended Project Structure (new files only)
```
services/web/src/
├── pages/
│   └── VideoDetailPage.tsx      # NEW: full detail page
├── api/
│   └── videos.ts                # EXTEND: add getVideo, getVideoDetections,
│                                #         getVideoFaces, deleteVideo hooks
└── types/
    └── api.ts                   # EXTEND: add VideoDetailItem, VideoDetectionItem,
                                 #         VideoFaceItem interfaces
```

**Modified files:**
- `services/web/src/App.tsx` — add `<Route path="videos/:id" element={<VideoDetailPage />} />`
- `services/web/src/pages/VideosPage.tsx` — row click nav + delete button

---

## Verified Codebase Patterns

### Pattern 1: Route Registration (App.tsx)
**File:** `services/web/src/App.tsx`
**Pattern:** All routes are children of `<Route path="/" element={<Layout />}>`. No nested sub-routes exist yet.

```tsx
// Current (App.tsx lines 13-20):
<Route path="/" element={<Layout />}>
  <Route index           element={<SearchPage />} />
  <Route path="videos"   element={<VideosPage />} />
  <Route path="people"   element={<PeoplePage />} />
  <Route path="clusters" element={<ClustersPage />} />
  <Route path="settings" element={<SettingsPage />} />
  <Route path="*"        element={<Navigate to="/" replace />} />
</Route>

// Add at same level:
<Route path="videos/:id" element={<VideoDetailPage />} />
```
[VERIFIED: App.tsx]

### Pattern 2: TanStack Query v5 useQuery (object form)
**File:** `services/web/src/api/videos.ts` (lines 38-46), `api/clusters.ts` (lines 45-53)

```ts
// Standard pattern — all hooks use this exact shape:
export function useVideoDetail(id: string) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['video', id],
    queryFn:  () => getVideo(id),
    staleTime: 15_000,
    enabled:   !!apiToken && !!id,
  });
}
```
[VERIFIED: api/videos.ts, api/clusters.ts, api/persons.ts — all use object-form v5]

### Pattern 3: useMutation + cache invalidation
**File:** `services/web/src/api/persons.ts` (lines 70-76)

```ts
export function useDeleteVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteVideo(id),
    onSuccess: (_data, id) => {
      // Invalidate all affected caches (DEL-04)
      qc.invalidateQueries({ queryKey: ['videos'] });
      qc.removeQueries({ queryKey: ['video', id] });
      // Invalidate search results (DEL-04: disappears from Search results)
      qc.invalidateQueries({ queryKey: ['search'] });
      // Clusters may reference this video's faces:
      qc.invalidateQueries({ queryKey: ['clusters'] });
    },
  });
}
```
[VERIFIED: pattern from api/persons.ts useDeletePerson + api/clusters.ts multi-key invalidation]

### Pattern 4: authFetch DELETE
**File:** `services/web/src/api/persons.ts` (line 34-36)

```ts
// Exact same shape used for deletePerson — works for deleteVideo too:
export async function deleteVideo(id: string): Promise<void> {
  await authFetch(`/videos/${id}`, { method: 'DELETE' });
  // authFetch injects Authorization: Bearer automatically
  // Throws on non-2xx (e.g. 401, 404, 500)
  // 204 No Content → response.ok is true → returns without throwing
}
```
[VERIFIED: api/client.ts authFetch, api/persons.ts deletePerson]

### Pattern 5: FrameThumbnail reuse for detections/faces grids
**File:** `services/web/src/components/FrameThumbnail.tsx`

Both `GET /videos/{id}/detections` and `GET /videos/{id}/faces` return a `frame_id: number` field. `FrameThumbnail` takes `frameId: number` and calls `getFrameImageUrl(frameId)` = `/api/frames/${frameId}/image`.

```tsx
// Detection card — FrameThumbnail is directly usable:
<FrameThumbnail
  frameId={detection.frame_id}
  alt={`${detection.label} at ${(detection.ts_ms/1000).toFixed(1)}s`}
  className="aspect-video rounded"
/>
```
[VERIFIED: FrameThumbnail.tsx, frames.ts getFrameImageUrl, API contract frame_id field]

### Pattern 6: Inline delete confirmation (existing — PersonCard)
**File:** `services/web/src/components/PersonCard.tsx` (lines 67-91)

The existing approach toggles a `confirmDelete` boolean, shows "Sure?" + "Yes, delete" + "Cancel":

```tsx
// From PersonCard.tsx — this exact pattern works for VideosPage row delete (DEL-01):
{!confirmDelete ? (
  <button onClick={() => setConfirmDelete(true)} className="...text-red-500...">Delete</button>
) : (
  <div className="flex gap-1 items-center">
    <span className="text-xs text-gray-600">Sure?</span>
    <button onClick={handleDelete} disabled={deletePerson.isPending} className="...text-red-600...">
      {deletePerson.isPending ? 'Deleting…' : 'Yes, delete'}
    </button>
    <button onClick={() => setConfirmDelete(false)} className="...">Cancel</button>
  </div>
)}
```
[VERIFIED: PersonCard.tsx lines 67-91]

### Pattern 7: Headless UI Dialog (for VideoDetailPage delete — DEL-02)
**File:** `services/web/src/components/VideoModal.tsx` (lines 47-153)

```tsx
// VideoModal shows the Dialog pattern already in use:
import { Dialog, DialogPanel, DialogTitle } from '@headlessui/react';

<Dialog open={showDeleteDialog} onClose={() => setShowDeleteDialog(false)} className="relative z-50">
  <div className="fixed inset-0 bg-black/60" aria-hidden="true" />
  <div className="fixed inset-0 flex items-center justify-center p-4">
    <DialogPanel className="bg-white rounded-xl shadow-2xl max-w-sm w-full p-6">
      <DialogTitle className="text-base font-semibold text-gray-900 mb-2">Delete video?</DialogTitle>
      <p className="text-sm text-gray-600 mb-5">This cannot be undone.</p>
      <div className="flex gap-3 justify-end">
        <button onClick={() => setShowDeleteDialog(false)} className="...">Cancel</button>
        <button onClick={handleDelete} disabled={deleteVideo.isPending} className="...bg-red-600...">
          {deleteVideo.isPending ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </DialogPanel>
  </div>
</Dialog>
```
[VERIFIED: VideoModal.tsx, @headlessui/react 2.2.4 in package.json]

### Pattern 8: Toast notification
**File:** `services/web/src/hooks/useToast.ts` + `components/PersonCard.tsx` (line 21)

```ts
// Call addToast from anywhere — no hook needed:
import { addToast } from '../hooks/useToast';
addToast('Video deleted', 'success');
addToast('Failed to delete video', 'error');
```
[VERIFIED: useToast.ts addToast, PersonCard.tsx usage]

### Pattern 9: Navigation in response to events
**File:** Referenced from react-router-dom 6.30.1

```tsx
// In VideoDetailPage after successful delete:
import { useNavigate, useParams } from 'react-router-dom';
const navigate = useNavigate();

// After deletion confirmed:
await deleteVideo.mutateAsync(id);
addToast('Video deleted', 'success');
navigate('/videos', { replace: true });  // replace: true so back button doesn't return to deleted page
```
[VERIFIED: react-router-dom 6.30.1 in package.json; useNavigate pattern standard RRv6]

### Pattern 10: Row-click navigation in VideosPage (VDP-01 / VDP-06)
**File:** `services/web/src/pages/VideosPage.tsx`

```tsx
// Add to VideosPage:
import { useNavigate } from 'react-router-dom';
const navigate = useNavigate();

// On the <tr>:
<tr
  className="hover:bg-gray-50 transition-colors cursor-pointer"
  onClick={() => navigate(`/videos/${video.id}`)}
>
```

**Important:** The Action column buttons (Re-ingest, Delete) must call `e.stopPropagation()` to prevent row click from firing when a button is clicked.
[VERIFIED: VideosPage.tsx row structure, react-router-dom pattern]

### Pattern 11: useParams for URL ID
```tsx
// In VideoDetailPage:
import { useParams } from 'react-router-dom';
const { id } = useParams<{ id: string }>();
```
[VERIFIED: react-router-dom 6.30.1; standard RRv6 pattern]

### Pattern 12: Existing grid + skeleton pattern
**File:** `services/web/src/pages/ClustersPage.tsx` (lines 49-54), `SearchPage.tsx` (lines 273-286)

```tsx
// Standard grid — reuse for detections and faces grids:
<div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
  {items.map(item => (
    <div key={item.id} className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
      <FrameThumbnail frameId={item.frame_id} className="w-full aspect-video" />
      <div className="p-2">
        <p className="text-xs font-medium text-gray-800">{item.label}</p>
        <p className="text-xs text-gray-500">{Math.round(item.confidence * 100)}%</p>
        <p className="text-xs text-gray-400">{(item.ts_ms / 1000).toFixed(1)}s</p>
      </div>
    </div>
  ))}
</div>

// Skeleton loading (match existing pattern):
{isLoading && (
  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
    {Array.from({ length: 8 }).map((_, i) => (
      <div key={i} className="aspect-[4/5] bg-gray-200 rounded-xl animate-pulse" />
    ))}
  </div>
)}
```
[VERIFIED: ClustersPage.tsx, SearchPage.tsx, PeoplePage.tsx — consistent skeleton pattern across all pages]

### Pattern 13: No-token banner (consistent across all pages)
**File:** All pages follow this pattern (VideosPage.tsx lines 32-41, PeoplePage.tsx lines 20-29)

```tsx
const { settings } = useSettings();
if (!settings.apiToken) {
  return (
    <div className="p-6">
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
        API token not configured.{' '}
        <Link to="/settings" className="font-medium underline">Go to Settings →</Link>
      </div>
    </div>
  );
}
```
[VERIFIED: consistent in all 5 existing pages]

### Pattern 14: Tab bar (DOES NOT EXIST — build from scratch)
No existing tab component. Recommended implementation:

```tsx
type Tab = 'detections' | 'faces';
const [activeTab, setActiveTab] = useState<Tab>('detections');

// Tab bar:
<div className="flex border-b border-gray-200 mb-4">
  {(['detections', 'faces'] as Tab[]).map(tab => (
    <button
      key={tab}
      onClick={() => setActiveTab(tab)}
      className={clsx(
        'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px capitalize transition-colors',
        activeTab === tab
          ? 'border-blue-600 text-blue-700'
          : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
      )}
    >
      {tab === 'detections'
        ? `Detections (${video.detection_count})`
        : `Faces (${video.face_count})`}
    </button>
  ))}
</div>
```
[ASSUMED: tab styling; matches Tailwind patterns in rest of codebase]

### Pattern 15: Timeline bar (VDP-05 — build from scratch)
Timeline is a horizontal bar with clickable marks at proportional positions.

```tsx
interface TimelineBarProps {
  faces: VideoFaceItem[];
  durationSec: number;
  videoRef: React.RefObject<HTMLVideoElement>;
}

function TimelineBar({ faces, durationSec, videoRef }: TimelineBarProps) {
  const durationMs = durationSec * 1000;

  function seek(tsMs: number) {
    if (videoRef.current) {
      videoRef.current.currentTime = tsMs / 1000;
    }
  }

  return (
    <div className="relative h-8 bg-gray-100 rounded-full mx-1 mt-3">
      {/* Track line */}
      <div className="absolute inset-y-0 left-0 right-0 flex items-center">
        <div className="w-full h-1 bg-gray-300 rounded-full" />
      </div>
      {/* Marks */}
      {faces.map(face => {
        const pct = durationMs > 0 ? (face.ts_ms / durationMs) * 100 : 0;
        return (
          <button
            key={face.id}
            title={`${face.person_name ?? 'Unknown'} at ${(face.ts_ms/1000).toFixed(1)}s`}
            onClick={() => seek(face.ts_ms)}
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-blue-500 hover:bg-blue-700 transition-colors hover:scale-125"
            style={{ left: `${pct}%` }}
          />
        );
      })}
    </div>
  );
}
```
[VERIFIED: native HTML5 video `currentTime` API; Tailwind classes consistent with existing codebase]

### Pattern 16: Video playback with seeking
**Current approach (VideoModal.tsx lines 34-37):** Opens presigned URL in a new browser tab with `#t=seconds` fragment. Does NOT embed `<video>`.

**New approach for VideoDetailPage:** Embed native `<video>` element. The `stream_url` from `GET /videos/{id}` response is used as `src`. This enables `videoRef.current.currentTime` control for timeline seeking.

```tsx
const videoRef = useRef<HTMLVideoElement>(null);

// stream_url comes from useVideoDetail response:
<video
  ref={videoRef}
  src={video.stream_url}
  controls
  className="w-full rounded-lg bg-black"
  preload="metadata"
/>
```

**Risk:** The `stream_url` is a presigned MinIO URL with a limited expiry (existing `UploadUrlResponse.expires_in = 3600`). The stream URL returned by `GET /videos/{id}` may also expire. If the user stays on the page for > 1 hour, the video will fail to load. Mitigation: re-fetch `GET /videos/{id}` if the video element fires an error event.
[VERIFIED: VideoModal.tsx for existing stream-url pattern; HTML5 video API standard]

---

## Type Definitions Required

**File:** `services/web/src/types/api.ts`

The following interfaces must be added (Phase 6 API contract, not yet in types/api.ts):

```ts
// GET /videos/{id} response
export interface VideoDetailItem {
  id:              string;
  minio_key:       string;
  filename:        string;          // NEW in Phase 6
  status:          'pending' | 'processing' | 'done' | 'failed';
  error_message:   string | null;
  recorded_at:     string | null;
  duration_sec:    number | null;
  frame_count:     number;
  detection_count: number;
  face_count:      number;
  ingested_at:     string;
  stream_url:      string;          // NEW in Phase 6 — presigned MinIO URL
}

// GET /videos/{id}/detections[] item
export interface VideoDetectionItem {
  id:            number;
  frame_id:      number;
  ts_ms:         number;
  thumbnail_url: string;    // "/frames/{id}/image" — relative
  label:         string;
  confidence:    number;
  bbox_json:     string;    // JSON string of bounding box
}

// GET /videos/{id}/faces[] item
export interface VideoFaceItem {
  id:               number;
  frame_id:         number;
  ts_ms:            number;
  thumbnail_url:    string;    // "/frames/{id}/image" — relative
  person_name:      string | null;   // null = unrecognized face
  appearance_count: number;
}
```
[VERIFIED: existing VideoListItem in types/api.ts as baseline; API contract from phase description; Phase 6 API spec adds filename + stream_url]

---

## API Client Extensions Required

**File:** `services/web/src/api/videos.ts` — add these functions and hooks:

```ts
// Fetch functions:
export async function getVideo(id: string): Promise<VideoDetailItem> {
  return authFetch(`/videos/${id}`).then(r => r.json());
}

export async function getVideoDetections(id: string): Promise<VideoDetectionItem[]> {
  return authFetch(`/videos/${id}/detections`).then(r => r.json());
}

export async function getVideoFaces(id: string): Promise<VideoFaceItem[]> {
  return authFetch(`/videos/${id}/faces`).then(r => r.json());
}

export async function deleteVideo(id: string): Promise<void> {
  await authFetch(`/videos/${id}`, { method: 'DELETE' });
}

// Hooks:
export function useVideoDetail(id: string) { ... }
export function useVideoDetections(id: string) { ... }
export function useVideoFaces(id: string) { ... }
export function useDeleteVideo() { ... }
```
[VERIFIED: authFetch pattern from client.ts; all existing hooks in api/*.ts as model]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dialog/confirmation UI | Custom modal overlay | `@headlessui/react` Dialog | Already installed, focus-trap, a11y, backdrop handling built-in |
| Lazy image loading | Custom IntersectionObserver | `loading="lazy"` on `<img>` (used in FrameThumbnail) | Native browser API, no JS needed |
| Toast notifications | Custom state-managed toasts | `addToast()` from `hooks/useToast.ts` | Already in app, global singleton |
| Video seek control | Custom seek bar UI | Native `<video controls>` + `videoRef.currentTime` | HTML5 video player handles all playback UI; only timeline marker clicks need custom code |
| Conditional CSS | Ternary string concatenation | `clsx` (already in every component) | Already imported everywhere |
| Auth headers | Manual `fetch()` with Bearer | `authFetch()` from `api/client.ts` | Reads token from localStorage, handles errors |

**Key insight:** Every cross-cutting concern (auth, toasts, loading states, image lazy-loading, modal dialogs) already has a project-standard solution. Build none of them from scratch.

---

## Common Pitfalls

### Pitfall 1: Row click fires when action button is clicked
**What goes wrong:** User clicks "Delete" or "Re-ingest" in the row's Action column, and `onClick` on the `<tr>` also fires, navigating to the detail page.
**Why it happens:** Event bubbling from button → td → tr.
**How to avoid:** Add `e.stopPropagation()` on all button click handlers in the Action column.
**Warning signs:** Delete dialog appears then immediately navigates away.

### Pitfall 2: stream_url expiry
**What goes wrong:** The presigned MinIO URL in `stream_url` expires (typically 1 hour). The `<video>` element shows an error after expiry.
**Why it happens:** MinIO presigned URLs have a TTL; `GET /videos/{id}` bakes the URL at request time.
**How to avoid:** Handle the `<video>` `onError` event by re-fetching `useVideoDetail` (invalidate query key `['video', id]`). Alternatively, refetch when the tab regains focus (TanStack Query's `refetchOnWindowFocus` is likely enabled by default).
**Warning signs:** Video loads initially but breaks after ~60 minutes.

### Pitfall 3: Unknown face name display
**What goes wrong:** `VideoFaceItem.person_name` is `null` for unrecognized faces; rendering `null` in JSX is silent but leaves an empty cell.
**Why it happens:** API returns `null`, not `"Unknown"`.
**How to avoid:** Use `face.person_name ?? 'Unknown'` for display. For VDP-04, the spec says "person name or 'Unknown Cluster #N'" — but `appearance_count` or a cluster label is not returned by `GET /videos/{id}/faces`. Use `'Unknown'` as fallback (cluster # is not available in this API response).
**Warning signs:** Blank labels in the Faces grid.

### Pitfall 4: TanStack Query v5 — no `onSuccess` on `useQuery`
**What goes wrong:** Developer writes `useQuery({ onSuccess: ... })` — this was removed in v5.
**Why it happens:** v4→v5 breaking change: `onSuccess`/`onError` callbacks removed from `useQuery`.
**How to avoid:** Use `useEffect` watching the query result, or handle success inline. For mutations, `onSuccess` on `useMutation` still works (that's the pattern used project-wide).
**Warning signs:** TypeScript error — `onSuccess` not a valid property of `useQuery` options.

### Pitfall 5: `useParams` returns `id: string | undefined`
**What goes wrong:** TypeScript error when passing `id` to query hooks that expect `string`.
**Why it happens:** `useParams<{ id: string }>()` returns `{ id: string | undefined }` in RR v6.
**How to avoid:**
```tsx
const { id } = useParams<{ id: string }>();
if (!id) return <Navigate to="/videos" replace />;
// After this guard, id is string
```
**Warning signs:** TS error `Argument of type 'string | undefined' is not assignable to parameter of type 'string'`.

### Pitfall 6: Back button after delete navigates to deleted-video page
**What goes wrong:** After deleting on VideoDetailPage, `navigate('/videos')` pushes a new history entry. User presses Back → returns to the now-invalid `/videos/:id` page. Page tries to fetch deleted video → 404 error state.
**How to avoid:** Use `navigate('/videos', { replace: true })` to replace the detail page entry in history.
**Warning signs:** Back button returns to an error screen showing "Video not found".

### Pitfall 7: Timeline marks overflow at 100% position
**What goes wrong:** A face at `ts_ms = duration_sec * 1000` renders at `left: 100%` and half the mark dot overflows the container.
**Why it happens:** `-translate-x-1/2` centers the mark but doesn't clamp to container bounds.
**How to avoid:** Cap position: `Math.min(pct, 97)` or use `clamp(3%, calc(${pct}% - 0px), 97%)`. Add `overflow-hidden` to the container.
**Warning signs:** Last timeline mark is partially clipped.

### Pitfall 8: Duplicate row data after delete (DEL-04)
**What goes wrong:** After delete, `Videos` page still shows the deleted row because the paginated query `['videos', page]` has a specific page key, and invalidating `['videos']` should clear all pages.
**Why it happens:** `invalidateQueries({ queryKey: ['videos'] })` does prefix-match in TanStack Query v5 — it WILL invalidate `['videos', 1]`, `['videos', 2]` etc. This is correct behavior.
**Confirmation:** Existing `useReIngestVideo` already does `qc.invalidateQueries({ queryKey: ['videos'] })` and it works for the paginated list. [VERIFIED: api/videos.ts lines 49-53]

---

## Re-usable Components (can be used directly)

| Component | File | Re-use for |
|-----------|------|-----------|
| `FrameThumbnail` | `components/FrameThumbnail.tsx` | Detection cards, Face cards (uses `frame_id`) |
| `StatusBadge` | `components/StatusBadge.tsx` | Video status on detail page header |
| `VideoModal` | `components/VideoModal.tsx` | Not re-used (detail page replaces this) |
| `addToast` | `hooks/useToast.ts` | Success/error feedback for delete |

---

## Gaps / New Utilities Required

| Gap | Location | Size |
|-----|----------|------|
| `VideoDetailPage` component | `pages/VideoDetailPage.tsx` | Large — primary deliverable |
| Tab bar (no component exists) | Inline in `VideoDetailPage.tsx` | Small — ~20 lines |
| `TimelineBar` component | Inline in `VideoDetailPage.tsx` or separate `components/TimelineBar.tsx` | Medium — ~40 lines |
| New types: `VideoDetailItem`, `VideoDetectionItem`, `VideoFaceItem` | `types/api.ts` | Small — ~30 lines |
| New API hooks: `useVideoDetail`, `useVideoDetections`, `useVideoFaces`, `useDeleteVideo` | `api/videos.ts` | Medium — ~60 lines |
| Route registration | `App.tsx` | Tiny — 1 line |
| Row click + delete button | `pages/VideosPage.tsx` | Small — ~25 lines changed |

---

## Implementation Recommendations Per Requirement

| Req | Implementation | Key Decision |
|-----|---------------|--------------|
| VDP-01 | `<tr onClick={() => navigate(\`/videos/${video.id}\`)}>` in VideosPage; also a `<Link to>` icon in Action col | Use `useNavigate` + `e.stopPropagation()` on buttons |
| VDP-02 | `useVideoDetail(id)` → render metadata; `<video ref={videoRef} src={video.stream_url} controls />` | Native `<video>` (not new-tab) |
| VDP-03 | `useVideoDetections(id)` → grid of `FrameThumbnail` + label/confidence/timestamp cards | Re-use `FrameThumbnail` with `frame_id` |
| VDP-04 | `useVideoFaces(id)` → grid of `FrameThumbnail` + `person_name ?? 'Unknown'` + timestamp | `null` → `'Unknown'` fallback |
| VDP-05 | `TimelineBar` inline component; `videoRef` from page; marks at `(ts_ms / durationMs) * 100%` | Pass `videoRef` as prop to TimelineBar |
| VDP-06 | Row click in VideosPage; dedicated 🔍 icon `<Link>` in Action column | Both navigation paths needed |
| DEL-01 | Inline "Sure?" pattern (PersonCard style) in VideosPage row Action column | `e.stopPropagation()` critical |
| DEL-02 | Headless UI Dialog in VideoDetailPage; `navigate('/videos', {replace: true})` on confirm | `replace: true` prevents back-to-deleted-page |
| DEL-04 | `qc.invalidateQueries(['videos'])` + `qc.removeQueries(['video', id])` + `qc.invalidateQueries(['search'])` + `qc.invalidateQueries(['clusters'])` | Prefix match covers paginated keys |

---

## Risk Flags

1. **🟡 MEDIUM — `stream_url` TTL expiry in embedded `<video>`:** The presigned URL expires. Handle `<video onError>` to re-fetch. Low probability during normal use but should be designed for.

2. **🟡 MEDIUM — Large detections/faces lists:** A video with 10,000 detections would render 10,000 thumbnail DOM nodes. The API contract doesn't show pagination for `/detections` or `/faces`. If lists can be large, consider virtual scrolling or limiting to first N results. Flag as a risk — check API behavior.

3. **🟢 LOW — `person_name` vs cluster label (VDP-04 spec says "Unknown Cluster #N"):** The `GET /videos/{id}/faces` API returns `person_name: null` for unrecognized faces but does NOT return a cluster ID. The spec text "Unknown Cluster #N" cannot be implemented with the Phase 6 API as described. Use `'Unknown'` as fallback. If cluster IDs are needed, API extension required.

4. **🟢 LOW — Mobile video player layout:** Native `<video>` with `controls` renders differently per browser on mobile. Set `className="w-full max-h-64 md:max-h-96 bg-black rounded-lg"` and test on mobile viewport.

5. **🟢 LOW — Timeline bar with 0 duration:** `video.duration_sec` could be `null` (pending/processing videos). Guard: `if (!video.duration_sec) return null` in TimelineBar.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| React Router v5 `useHistory` | React Router v6 `useNavigate` | Use `useNavigate`, not `useHistory` |
| TanStack Query v4 `onSuccess` on `useQuery` | v5: removed from `useQuery`, still on `useMutation` | Don't add `onSuccess` to `useQuery` |
| `<a href>` for in-app links | `<Link to>` / `useNavigate` | All navigation via RR components |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `GET /videos/{id}` returns `stream_url` field directly (not requiring separate `/stream-url` call) | Pattern 16, Type Definitions | Would need extra API call to get stream URL before rendering player |
| A2 | `GET /videos/{id}/detections` and `/faces` return full lists (not paginated) | Pattern 15, Risk Flags | Large videos could have thousands of items; need pagination or virtual scroll |
| A3 | `thumbnail_url` in detections/faces responses is a path like `/frames/{id}/image` (consistent with FrameResult.thumbnail_url) | Pattern 5 | If it's a different shape, FrameThumbnail would need a raw-URL variant |
| A4 | Tab bar component is best built inline in VideoDetailPage (not a separate reusable component) | Gaps section | Acceptable either way; inline is simpler for first implementation |

---

## Environment Availability

Step 2.6: SKIPPED — this phase is purely frontend code changes. No new external dependencies; all required tools (Node, npm, React dev server) are already present and used by the existing web service.

---

## Validation Architecture

`workflow.nyquist_validation` is `false` in `.planning/config.json` — Validation Architecture section skipped.

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | `authFetch()` injects `Authorization: Bearer` from localStorage — already project standard |
| V4 Access Control | Yes | `DELETE /videos/{id}` requires Bearer token — enforced by API layer; frontend passes token via `authFetch` |
| V5 Input Validation | Low | No user-generated input on this page (read-only display + delete action) |

**Key security note:** The `stream_url` is a presigned URL generated by the API (MinIO). It is served directly to the browser as the `<video src>`. This URL is not a secret — it is a time-limited access URL. Do not log or expose it beyond the video element's `src` attribute.
[VERIFIED: authFetch pattern in client.ts; Bearer token pattern used across all mutations]

---

## Sources

### Primary (HIGH confidence — VERIFIED from codebase)
- `services/web/src/App.tsx` — router structure
- `services/web/src/api/client.ts` — authFetch, getSettings, Bearer token pattern
- `services/web/src/api/videos.ts` — existing hooks, query keys, mutation patterns
- `services/web/src/api/persons.ts` — deletePerson, useDeletePerson pattern (model for delete)
- `services/web/src/api/clusters.ts` — multi-key invalidation pattern
- `services/web/src/api/frames.ts` — getFrameImageUrl
- `services/web/src/types/api.ts` — VideoListItem, FrameResult, all existing types
- `services/web/src/components/FrameThumbnail.tsx` — thumbnail component API
- `services/web/src/components/VideoModal.tsx` — Headless UI Dialog pattern, stream-url pattern
- `services/web/src/components/PersonCard.tsx` — inline delete confirmation pattern, addToast usage
- `services/web/src/components/ClusterCard.tsx` — card + action button layout
- `services/web/src/components/StatusBadge.tsx` — badge reuse
- `services/web/src/hooks/useToast.ts` — addToast API
- `services/web/src/pages/VideosPage.tsx` — table structure, pagination, row layout
- `services/web/src/pages/SearchPage.tsx` — grid + FrameThumbnail usage
- `services/web/src/pages/ClustersPage.tsx` — grid + skeleton pattern
- `services/web/src/pages/PeoplePage.tsx` — grid + card pattern
- `services/web/package.json` — exact package versions

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — exact versions from package.json
- Architecture: HIGH — patterns derived directly from existing source files
- Pitfalls: HIGH (code-derived) / MEDIUM (A1-A4 assumptions)
- New component patterns (tabs, timeline): MEDIUM — consistent with codebase style but no direct precedent

**Research date:** 2025-07-22
**Valid until:** Stable — only changes if Phase 6 API contract changes or package versions bump
