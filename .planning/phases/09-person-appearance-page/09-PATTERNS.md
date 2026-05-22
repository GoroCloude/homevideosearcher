# Phase 9: Person Appearance Page — Pattern Map

**Mapped:** 2025-01-31
**Files analyzed:** 8 target files/concerns
**Analogs found:** 7 / 8 (1 no-analog: `useSearchParams` — new pattern to codebase)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/web/src/pages/PersonAppearancePage.tsx` | page/component | request-response | `services/web/src/pages/VideoDetailPage.tsx` | exact |
| `services/web/src/App.tsx` (add route) | config/router | — | `services/web/src/App.tsx` lines 20 | exact |
| `services/web/src/pages/PeoplePage.tsx` (add click handler) | page/component | — | existing file lines 128–133 | exact |
| `services/web/src/api/persons.ts` (add hook) | api/hook | request-response | `services/web/src/api/persons.ts` lines 44–52 | exact |
| `services/web/src/types/api.ts` (add types) | types | — | `services/web/src/types/api.ts` lines 114–146 | exact |
| `services/api/app/persons.py` (add endpoint) | API route | CRUD | `services/api/app/persons.py` lines 378–454 | exact |
| VideoDetailPage `?t=` seek-on-mount | feature/hook | — | `VideoDetailPage.tsx` lines 55–57 (seek fn) | role-match (extend) |
| Timeline/calendar date grouping UI | component | transform | `VideoDetailPage.tsx` lines 207–225 (timeline bar) | partial |

---

## Pattern Assignments

### 1. Detail Page Route Pattern
**For:** `PersonAppearancePage.tsx` overall skeleton
**Analog:** `services/web/src/pages/VideoDetailPage.tsx` (entire file, 305 lines)

**Route registration pattern** (`App.tsx` line 20 — clone for people):
```tsx
// services/web/src/App.tsx, line 20
<Route path="videos/:id" element={<VideoDetailPage />} />

// NEW — add directly below it:
<Route path="people/:id" element={<PersonAppearancePage />} />
```

**Page scaffold pattern** (lines 30–53 — copy the no-token guard, useParams, isLoading, isError blocks):
```tsx
// VideoDetailPage.tsx lines 30–97
export default function VideoDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { settings } = useSettings();
  const { data: video, isLoading, isError, error } = useVideoDetail(id ?? '');

  // No-token guard — app-standard amber banner
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

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-6 w-48 bg-gray-200 rounded animate-pulse" />
        <div className="h-56 bg-gray-200 rounded animate-pulse" />
      </div>
    );
  }

  // Error / not found
  if (isError || !video) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          Failed to load video:{' '}
          {error instanceof Error ? error.message : 'Not found'}
        </div>
        <button onClick={() => navigate('/videos')} className="mt-4 text-sm text-blue-600 hover:underline">
          ← Back to Videos
        </button>
      </div>
    );
  }
  // ... page body
}
```

**Back navigation + metadata header pattern** (lines 100–134):
```tsx
// VideoDetailPage.tsx lines 100–134
return (
  <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-6">
    <button onClick={() => navigate('/videos')} className="text-sm text-blue-600 hover:underline">
      ← Back to Videos
    </button>
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      <h1 className="text-base font-semibold text-gray-900 font-mono break-all mb-4">
        {video.filename}
      </h1>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3 text-sm">
        <div>
          <dt className="text-xs uppercase tracking-wide text-gray-400 mb-0.5">Status</dt>
          <dd className="text-gray-800 capitalize">{video.status}</dd>
        </div>
        {/* ... more fields */}
      </dl>
    </div>
  </div>
);
```

---

### 2. Per-Person API Endpoint (`GET /persons/{id}/appearances`)
**For:** new endpoint in `services/api/app/persons.py`
**Analog:** `services/api/app/persons.py` lines 358–454 (`GET /persons/{person_id}/faces`)

**Pydantic response model pattern** (lines 361–376):
```python
# persons.py lines 361–376
class PersonFaceResult(BaseModel):
    face_detection_id: int
    frame_id:          int
    video_id:          str
    ts_ms:             int
    match_tier:        Optional[str]
    match_similarity:  Optional[float]
    det_score:         Optional[float]
    thumbnail_url:     str    # /frames/{frame_id}/image

class PersonFacesResponse(BaseModel):
    person_id:  str
    results:    list[PersonFaceResult]
    pagination: dict
```

**Router endpoint shape** (lines 378–395 — copy signature, person-exists check, pagination):
```python
# persons.py lines 378–403
@router.get("/{person_id}/faces", response_model=PersonFacesResponse)
async def list_person_faces(
    person_id: UUID,
    page: int = 1,
    page_size: int = 20,
) -> PersonFacesResponse:
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be >= 1")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=422, detail="page_size must be 1–100")

    pool = await get_pool()

    # Verify person exists
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM known_persons WHERE id = $1", person_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Person not found")

    offset = (page - 1) * page_size
    # ...
```

**SQL GROUP BY + presigned URL per row pattern** (lines 405–443):
```python
# persons.py lines 405–443 — adapt GROUP BY video_id for appearances endpoint
rows = await conn.fetch(
    """
    SELECT
        fd.id   AS face_detection_id,
        fd.frame_id,
        f.video_id::text,
        f.ts_ms,
        fd.match_tier,
        fd.match_similarity,
        fd.det_score
    FROM face_detections fd
    JOIN frames f ON f.id = fd.frame_id
    WHERE fd.matched_person_id = $1
    ORDER BY f.ts_ms DESC
    LIMIT $2 OFFSET $3
    """,
    person_id,
    page_size,
    offset,
)
# NEW appearances endpoint will group by video_id and use MIN(f.ts_ms), COUNT(*):
# SELECT f.video_id::text, MIN(f.ts_ms) AS first_ts_ms, COUNT(*) AS face_count,
#        v.minio_key, v.recorded_at::text, v.duration_sec, fd_first.frame_id AS thumb_frame_id
# FROM face_detections fd JOIN frames f ... JOIN videos v ... WHERE fd.matched_person_id = $1
# GROUP BY f.video_id, v.minio_key, v.recorded_at, v.duration_sec, fd_first.frame_id
# ORDER BY MIN(v.recorded_at) DESC (or MIN(v.ingested_at) DESC)
```

**Presigned URL generation per result row** (lines 431–443):
```python
# persons.py lines 431–443 / videos.py lines 262–276
results = [
    PersonFaceResult(
        ...
        thumbnail_url=f"/frames/{r['frame_id']}/image",  # existing: relative path
    )
    for r in rows
]
# For appearances endpoint use generate_presigned_url() directly (like videos.py lines 267–271):
thumbnail_url=generate_presigned_url(
    bucket=config.MINIO_BUCKET_FRAMES,
    key=r["frame_minio_key"],
    expires_hours=1,
),
```

---

### 3. PersonCard Component (adding navigation)
**For:** `services/web/src/pages/PeoplePage.tsx` — wrap `<PersonCard>` in a clickable link
**Analog:** `services/web/src/pages/PeoplePage.tsx` lines 128–133

**Current card render pattern** (lines 128–133 — wrap with `<Link>` or add `onClick`):
```tsx
// PeoplePage.tsx lines 128–133
{persons.length > 0 && (
  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
    {persons.map(person => (
      <PersonCard key={person.id} person={person} />
    ))}
  </div>
)}
// Modify to: wrap each PersonCard with <Link to={`/people/${person.id}`}>
// PersonCard already handles its own click events (delete, rematch, dropzone)
// — use a header-level Link inside PersonCard or pass an onNavigate prop
```

**PersonCard internal layout** (`PersonCard.tsx` lines 34–48 — add link on the name/header):
```tsx
// PersonCard.tsx lines 34–48 — the header block is the click target
<div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col gap-3">
  <div className="flex items-start justify-between gap-2">
    <div>
      <h3 className="font-semibold text-gray-900">{person.name}</h3>
      <p className="text-xs text-gray-500 mt-0.5">
        {person.enrollment_count} enrollment{person.enrollment_count !== 1 ? 's' : ''}
      </p>
    </div>
    <div className="text-2xl select-none">👤</div>
  </div>
  {/* ... actions */}
</div>
```

---

### 4. useQuery Hook Pattern (TanStack Query v5)
**For:** new `usePersonAppearances(id)` hook in `services/web/src/api/persons.ts`
**Analog:** `services/web/src/api/persons.ts` lines 44–52 / `services/web/src/api/videos.ts` lines 98–106

**Exact hook shape to copy** (persons.ts lines 44–52):
```typescript
// persons.ts lines 44–52
export function usePersons() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['persons'],
    queryFn:  listPersons,
    staleTime: 30_000,
    enabled: !!apiToken,   // don't fire without a token
  });
}

// New hook to add — same shape, parameterized by id:
export function usePersonAppearances(personId: string) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['person-appearances', personId],
    queryFn:  () => getPersonAppearances(personId),
    staleTime: 30_000,
    enabled:   !!apiToken && !!personId,
  });
}
```

**authFetch raw function shape** (persons.ts lines 7–9):
```typescript
// persons.ts lines 7–9
export async function listPersons(): Promise<PersonResponse[]> {
  return authFetch('/persons').then(r => r.json());
}

// New raw function:
export async function getPersonAppearances(personId: string): Promise<PersonAppearancesResponse> {
  return authFetch(`/persons/${personId}/appearances`).then(r => r.json());
}
```

---

### 5. URL Search Param Reading (`?t=ts_ms`)
**For:** VideoDetailPage modification — read `?t=` on mount and seek the video player
**Analog:** ⚠️ **NO ANALOG** — `useSearchParams` is not currently used anywhere in the codebase

**Pattern to introduce** (react-router-dom, already a dependency per App.tsx line 1):
```tsx
// New pattern — no existing analog; use react-router-dom's useSearchParams:
import { useParams, useSearchParams } from 'react-router-dom';

export default function VideoDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const seekToMs = searchParams.get('t');   // e.g. "12345" (ms) or null

  // After video metadata loads and videoRef is attached, seek once:
  useEffect(() => {
    if (seekToMs && videoRef.current) {
      videoRef.current.currentTime = Number(seekToMs) / 1000;
    }
  }, [seekToMs, video]);  // video dep ensures stream_url is loaded first
  // ...
}
```

---

### 6. HTML5 Video Player Seek (`videoRef.currentTime`)
**For:** VideoDetailPage seek-on-mount from `?t=ts_ms`
**Analog:** `services/web/src/pages/VideoDetailPage.tsx` lines 33 + 55–57

**Existing ref + seek pattern** (lines 33, 55–57):
```tsx
// VideoDetailPage.tsx line 33
const videoRef = useRef<HTMLVideoElement>(null);

// VideoDetailPage.tsx lines 55–57 — seek function already in file
function seek(ts_ms: number) {
  if (videoRef.current) videoRef.current.currentTime = ts_ms / 1000;
}

// Video element line 138–143
<video
  ref={videoRef}
  src={video.stream_url}
  controls
  className="w-full max-h-96"
/>
```
**Extend:** call the existing `seek()` fn inside a `useEffect` that fires when `video` (stream_url) first becomes defined and `seekToMs` is present.

---

### 7. Presigned URL Generation (server-side, face thumbnails)
**For:** `GET /persons/{id}/appearances` endpoint — thumbnail per video group
**Analog:** `services/api/app/videos.py` lines 262–277 (list_video_detections) + `services/api/app/storage.py` lines 56–68

**Import pattern** (videos.py line 21 — already imported in persons.py via faces endpoint):
```python
# videos.py line 21
from .storage import generate_presigned_url, generate_presigned_upload_url, get_minio_client

# persons.py — add to existing imports at top of file:
from .storage import generate_presigned_url
```

**Per-row presigned URL call** (videos.py lines 267–271):
```python
# videos.py lines 267–271 — copy this for each appearance row
thumbnail_url=generate_presigned_url(
    bucket=config.MINIO_BUCKET_FRAMES,
    key=r["frame_minio_key"],   # minio_key from frames table
    expires_hours=1,
),
```

**storage.py function signature** (lines 56–68 — no changes needed):
```python
# storage.py lines 56–68
def generate_presigned_url(bucket: str, key: str, expires_hours: int = 1) -> str:
    """Generate a presigned GET URL valid for `expires_hours` hours."""
    client = get_public_minio_client()   # MUST use public client for browser-resolvable URLs
    url = client.presigned_get_object(
        bucket_name=bucket,
        object_name=key,
        expires=timedelta(hours=expires_hours),
    )
    return url
```

---

### 8. Timeline / Date Grouping UI
**For:** Chronological calendar/timeline component on PersonAppearancePage
**Analog:** `services/web/src/pages/VideoDetailPage.tsx` lines 207–225 (faces timeline bar — partial match)

**Existing timeline bar pattern** (lines 207–225 — proportional position along a bar):
```tsx
// VideoDetailPage.tsx lines 207–225 — existing linear timeline within one video
{faces.length > 0 && video.duration_sec != null && (
  <div className="mb-4">
    <p className="text-xs text-gray-400 mb-1">Timeline — click to seek</p>
    <div className="relative h-8 bg-gray-100 rounded-full overflow-hidden w-full">
      {faces.map(f => (
        <button
          key={f.id}
          className="absolute top-0 h-full w-1 bg-blue-500 hover:bg-blue-700 transition-colors"
          style={{
            left: `${(f.ts_ms / (video.duration_sec! * 1000)) * 100}%`,
          }}
          onClick={() => seek(f.ts_ms)}
          title={`${f.person_name} at ${(f.ts_ms / 1000).toFixed(1)}s`}
        />
      ))}
    </div>
  </div>
)}
```
**Adapt for calendar:** group appearances by `recorded_at` date using `date-fns` (already imported in VideoDetailPage line 3: `import { format, parseISO } from 'date-fns'`). Render one row/badge per year-month or per video rather than a proportional bar.

**date-fns import** (VideoDetailPage.tsx line 3 — already in project):
```tsx
import { format, parseISO } from 'date-fns';
// Usage: format(parseISO(appearance.recorded_at), 'MMM yyyy')  → "Jan 2024"
```

---

## Shared Patterns

### No-Token Guard
**Source:** `services/web/src/pages/VideoDetailPage.tsx` lines 44–53
**Apply to:** `PersonAppearancePage.tsx`
```tsx
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

### Loading Skeleton
**Source:** `services/web/src/pages/VideoDetailPage.tsx` lines 71–79
**Apply to:** `PersonAppearancePage.tsx`
```tsx
if (isLoading) {
  return (
    <div className="p-6 space-y-4">
      <div className="h-6 w-48 bg-gray-200 rounded animate-pulse" />
      <div className="h-56 bg-gray-200 rounded animate-pulse" />
      <div className="h-40 bg-gray-200 rounded animate-pulse" />
    </div>
  );
}
```

### Error Banner
**Source:** `services/web/src/pages/VideoDetailPage.tsx` lines 82–97
**Apply to:** `PersonAppearancePage.tsx`
```tsx
if (isError || !data) {
  return (
    <div className="p-6">
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
        Failed to load: {error instanceof Error ? error.message : 'Not found'}
      </div>
      <button onClick={() => navigate('/people')} className="mt-4 text-sm text-blue-600 hover:underline">
        ← Back to People
      </button>
    </div>
  );
}
```

### authFetch + Error Throw
**Source:** `services/web/src/api/client.ts` lines 16–37
**Apply to:** new `getPersonAppearances()` raw function — no changes needed, just call `authFetch()`

### FastAPI Router Registration
**Source:** `services/api/app/persons.py` lines 23 + `services/api/app/main.py` (router.include)
**Apply to:** new `/appearances` endpoint is added to the existing `router` in `persons.py` — no new router registration needed

---

## No Analog Found

| Concern | Reason |
|---|---|
| `useSearchParams` (reading `?t=ts_ms`) | No query-string reading exists anywhere in the React app today. Use react-router-dom `useSearchParams` (already a transitive dep via `react-router-dom` in App.tsx). Pattern documented in #5 above using official react-router-dom API. |

---

## Metadata

**Analog search scope:** `services/web/src/`, `services/api/app/`
**Files read:** VideoDetailPage.tsx, PeoplePage.tsx, PersonCard.tsx, App.tsx, persons.py, videos.py, storage.py, api/persons.ts, api/videos.ts, api/client.ts, types/api.ts
**Pattern extraction date:** 2025-01-31
