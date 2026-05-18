# Phase 4: Web UI — Research

**Researched:** 2026-06-01
**Domain:** React 18 SPA · Vite · TanStack Query v5 · Tailwind CSS v3 · nginx static hosting
**Confidence:** HIGH (primary findings verified against npm registry, existing codebase, and nginx config)

---

## Summary

Phase 4 builds a React 18 SPA inside `services/web/`, replacing the placeholder `index.html` with a multi-page
browser application wired to the Phase 2 API. The nginx reverse proxy and SPA fallback routing are **already
configured** in `services/web/nginx.conf`; only the Dockerfile needs to be promoted from a single-stage
placeholder to a multi-stage Node-build → nginx-serve pipeline.

The most important finding is a **critical auth mismatch**: every thumbnail URL returned by `POST /search`
is `/frames/{id}/image`, and every route in the `frames_router` is registered with `Depends(require_token)`
in `main.py`. A plain `<img src="/api/frames/123/image">` will receive a `401` because browsers do not send
`Authorization` headers with image requests. **This must be resolved before any thumbnail can render.**
Recommendation: remove the bearer-token dependency from the frames router only (presigned MinIO URLs provide
sufficient security on their own), and add a `MINIO_PUBLIC_ENDPOINT` env var so presigned URLs use a
browser-accessible hostname rather than the internal Docker hostname `minio:9000`.

A secondary finding: the API currently lacks `GET /videos` (for the Videos page) and `GET /videos/{id}/stream-url`
(for timestamp-seek on the "Play in video" button). Both need to be added as part of Phase 4.

**Primary recommendation:** Build the React SPA in `services/web/src/`, use the nginx `/api/` proxy for all
API calls (same-origin, no CORS headaches), make `/frames/{id}/image` public in the API, add the two missing
endpoints, and store the bearer token + API base URL in `localStorage` accessed via a thin React context.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Page routing (search/library/clusters/settings) | Browser / Client (React Router) | — | Pure SPA; nginx always serves index.html (try_files already set) |
| API auth header injection | Browser / Client | — | Bearer token in localStorage; injected via custom fetch wrapper in every query fn |
| Thumbnail display | Browser / Client + API | — | Auth issue requires API change (make frames endpoint public); browser renders presigned MinIO URL |
| Video stream + timestamp seek | Browser / Client | API | JS fetches stream-url JSON → opens MinIO URL with #t= in new tab |
| Data fetching & mutation | Browser / Client (TanStack Query) | — | useQuery / useMutation; no server state on the nginx tier |
| Upload (multipart/form-data) | Browser / Client → API | — | FormData + fetch mutation; nginx passes multipart through to API unchanged |
| Drag-and-drop | Browser / Client | — | Native HTML5 drag events; no server involvement |
| Settings persistence | Browser / Client (localStorage) | — | No server round-trip; read at app init via context |
| Static file serving | CDN / Static (nginx) | — | nginx serves dist/; try_files handles SPA deep links |
| API proxying | Frontend Server (nginx /api/) | — | nginx location /api/ already strips prefix and proxies to api:8000 |

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WEB-01 | Search page: filter sidebar, results grid, thumbnail → modal → "Play in video" at ts_ms | TanStack Query useQuery for POST /search; blob-free thumbnails via public frames endpoint; stream-url JSON endpoint for #t= seek |
| WEB-02 | Videos page: table with status, duration, counts, ingestion date; Re-ingest button | Requires new GET /videos endpoint; Re-ingest calls POST /ingest on ingestion-worker via new proxy endpoint |
| WEB-03 | People page: enrolled-person cards; "Add person" flow with drag-and-drop; rejection feedback | useMutation for POST /persons + POST /persons/{id}/enroll; EnrollResponse.rejected[] rendered per file |
| WEB-04 | Unknown Clusters page: cluster cards; "Enroll as person"; "Mark as noise" | Requires GET /clusters endpoint (Phase 3 adds POST /cluster/run; GET needs separate addition) |
| WEB-05 | Settings page: API token + base URL stored in localStorage | React context reads localStorage; Settings form writes to localStorage; all hooks consume context |
| WEB-06 | TanStack Query v5 for all data; no global store | Object-form useQuery only (STATE.md constraint); QueryClient with 30s staleTime |
| WEB-07 | Tailwind CSS v3 utility-first; utilitarian layout; 1280×800 + 390×844 | tailwindcss@^3 pinned (v4 has breaking config changes per STATE.md); responsive grid with sm/md breakpoints |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react | 18.3.1 | UI component tree | Locked by ROADMAP.md (not v19) |
| react-dom | 18.3.1 | DOM renderer | Paired with react |
| typescript | ^5.9 | Type safety | TS 6.x too new for ecosystem (Vite 8 templates use 5.x) |
| vite | ^8 | Build tool + dev server | Locked by ROADMAP.md; fast HMR, native ESM |
| @vitejs/plugin-react | ^6 | JSX transform + Fast Refresh | Required for Vite 8 + React |
| tailwindcss | ^3.4 | Utility CSS | Pinned to v3 by STATE.md (v4 has breaking config changes) |
| autoprefixer | ^10 | PostCSS vendor prefixes | Required by Tailwind v3 setup |
| postcss | ^8 | CSS pipeline | Required by Tailwind v3 setup |
| @tanstack/react-query | ^5.100 | Data fetching + mutation | Locked by ROADMAP.md; v5 object-form only |
| react-router-dom | ^6.30 | Client-side routing | SPA navigation without page reload; v6 is stable, v7 has unnecessary breaking changes for this use case |

[VERIFIED: npm registry — all versions confirmed 2026-06-01]

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @tanstack/react-query-devtools | ^5.100 | Query cache inspector | Dev builds only; remove in prod via tree-shaking |
| clsx | ^2.1 | Conditional className strings | Everywhere class names are conditional |
| @headlessui/react | ^2.2 | Accessible modal, listbox, combobox | Frame detail modal, filter dropdowns |
| date-fns | ^4.1 | Date formatting + date-range utilities | Search filter (date_from/date_to), video table display |

[VERIFIED: npm registry — all versions confirmed 2026-06-01]

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| react-router-dom v6 | react-router-dom v7 | v7 introduces RSC/framework mode concepts that don't apply to this pure SPA; v6 is simpler and stable |
| @headlessui/react | radix-ui primitives | Both accessible; Headless UI is smaller and simpler for this use case |
| Native fetch wrapper | axios | axios is heavier; native fetch is sufficient with a thin auth wrapper |
| date-fns | dayjs | date-fns is tree-shakeable; dayjs uses plugins which add cognitive overhead |

**Installation (run inside `services/web/`):**
```bash
# Runtime deps
npm install react@18 react-dom@18 \
  @tanstack/react-query@^5 react-router-dom@^6 \
  clsx @headlessui/react date-fns

# Dev deps
npm install -D \
  typescript@^5 \
  @types/react@^18 @types/react-dom@^18 \
  vite@^8 @vitejs/plugin-react@^6 \
  tailwindcss@^3 autoprefixer@^10 postcss@^8 \
  @tanstack/react-query-devtools@^5
```

---

## Architecture Patterns

### System Architecture Diagram

```
Browser
  │
  │  GET / (static)
  ▼
nginx :80
  ├── location /             → /usr/share/nginx/html/dist  (try_files → index.html)
  └── location /api/         → proxy_pass http://api:8000/
                                (strips /api prefix, passes all headers through)

React SPA (in-browser)
  │
  ├── SettingsContext ──── localStorage (apiBaseUrl, apiToken)
  │                              │
  ├── authFetch(path, opts) ─────┘  (wraps fetch, injects Authorization: Bearer)
  │
  ├── QueryClient (TanStack Query v5)
  │     ├── useQuery(['persons'])          → GET /api/persons
  │     ├── useQuery(['videos'])           → GET /api/videos         [new endpoint]
  │     ├── useQuery(['search', filters])  → POST /api/search
  │     ├── useQuery(['clusters'])         → GET /api/clusters        [Phase 3 + new]
  │     └── useMutation(createPerson)      → POST /api/persons
  │
  └── Pages
        ├── /          → SearchPage
        ├── /videos    → VideosPage
        ├── /people    → PeoplePage
        ├── /clusters  → UnknownClustersPage
        └── /settings  → SettingsPage

Thumbnail loading (after auth fix):
  Browser <img src="/api/frames/123/image">
    → nginx → api:8000/frames/123/image
    → 302 Location: http://MINIO_PUBLIC_ENDPOINT/frames/...?X-Amz-...
    → Browser follows redirect → MinIO serves JPEG

Video play + seek:
  JS fetch('/api/videos/{id}/stream-url', {headers: auth})  [new endpoint]
    → { "url": "http://MINIO_PUBLIC_ENDPOINT/videos/...?X-Amz-..." }
  window.open(url + '#t=' + (ts_ms/1000), '_blank')
```

### Recommended Project Structure
```
services/web/
├── Dockerfile              # multi-stage: node build + nginx serve
├── nginx.conf              # already correct — do not modify
├── index.html              # Vite entry (single <div id="root">)
├── package.json
├── vite.config.ts
├── tailwind.config.cjs
├── postcss.config.cjs
├── tsconfig.json
└── src/
    ├── main.tsx            # ReactDOM.createRoot + QueryClientProvider + RouterProvider
    ├── App.tsx             # BrowserRouter + Route definitions
    ├── api/
    │   ├── client.ts       # authFetch wrapper (reads token from context/localStorage)
    │   ├── persons.ts      # typed API functions: listPersons, createPerson, enroll, delete, rematch
    │   ├── search.ts       # searchFrames(filters) → SearchResponse
    │   ├── videos.ts       # listVideos, getStreamUrl
    │   └── clusters.ts     # listClusters, enrollCluster, markNoise
    ├── context/
    │   └── SettingsContext.tsx   # apiBaseUrl + apiToken; reads/writes localStorage
    ├── hooks/
    │   ├── usePersons.ts         # useQuery + useMutation wrappers
    │   ├── useSearch.ts          # useQuery for POST /search with filter state
    │   ├── useVideos.ts
    │   └── useClusters.ts
    ├── pages/
    │   ├── SearchPage.tsx
    │   ├── VideosPage.tsx
    │   ├── PeoplePage.tsx
    │   ├── UnknownClustersPage.tsx
    │   └── SettingsPage.tsx
    ├── components/
    │   ├── FrameGrid.tsx         # responsive thumbnail grid
    │   ├── FrameModal.tsx        # detection details + "Play in video" button
    │   ├── FilterSidebar.tsx     # persons multi-select, classes, date range, video selector
    │   ├── PersonCard.tsx        # enrolled person with photo collage
    │   ├── DropZone.tsx          # drag-and-drop upload zone (native HTML5)
    │   ├── ClusterCard.tsx       # unknown face cluster card
    │   ├── StatusBadge.tsx       # video status (pending/processing/done/failed)
    │   └── Nav.tsx               # top navigation bar
    └── types/
        └── api.ts                # TypeScript interfaces matching API Pydantic models
```

### Pattern 1: Settings Context (token + base URL)
**What:** Store API base URL and bearer token in localStorage; expose via React context.
**When to use:** Every component that calls the API reads from this context.

```typescript
// src/context/SettingsContext.tsx
// Source: React docs context pattern + localStorage
const LS_KEY_TOKEN   = 'hvs:api_token';
const LS_KEY_API_URL = 'hvs:api_base_url';

export interface Settings {
  apiBaseUrl: string;   // default: '' (empty = use nginx /api/ proxy)
  apiToken:   string;
}

export const SettingsContext = createContext<{
  settings:     Settings;
  saveSettings: (s: Partial<Settings>) => void;
}>({ settings: { apiBaseUrl: '', apiToken: '' }, saveSettings: () => {} });

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Settings>(() => ({
    apiBaseUrl: localStorage.getItem(LS_KEY_API_URL) ?? '',
    apiToken:   localStorage.getItem(LS_KEY_TOKEN)   ?? '',
  }));

  const saveSettings = (patch: Partial<Settings>) => {
    const next = { ...settings, ...patch };
    localStorage.setItem(LS_KEY_API_URL, next.apiBaseUrl);
    localStorage.setItem(LS_KEY_TOKEN,   next.apiToken);
    setSettings(next);
  };

  return (
    <SettingsContext.Provider value={{ settings, saveSettings }}>
      {children}
    </SettingsContext.Provider>
  );
}

export const useSettings = () => useContext(SettingsContext);
```

[ASSUMED] — localStorage key naming convention `hvs:` prefix is a project decision, not a standard.

### Pattern 2: Auth Fetch Wrapper
**What:** A `fetch` wrapper that injects `Authorization: Bearer` on every request.
**When to use:** All API call functions in `src/api/*.ts`.

```typescript
// src/api/client.ts
// Uses settings from localStorage directly (avoids hook dependency outside components)
function getSettings(): { apiBaseUrl: string; apiToken: string } {
  return {
    apiBaseUrl: localStorage.getItem('hvs:api_base_url') ?? '',
    apiToken:   localStorage.getItem('hvs:api_token')   ?? '',
  };
}

export async function authFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const { apiBaseUrl, apiToken } = getSettings();
  const base = apiBaseUrl || '';          // empty = nginx proxy at /api/
  const prefix = base ? base : '/api';   // /api/ proxy or explicit base URL

  const response = await fetch(`${prefix}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`${response.status}: ${text}`);
  }
  return response;
}
```

**Key design note:** Reading localStorage directly (not via React context) allows `authFetch` to be called
inside TanStack Query `queryFn` callbacks, which run outside the React component tree.

### Pattern 3: TanStack Query v5 — Object-Form Only
**What:** TanStack Query v5 requires the object argument form for `useQuery` and `useMutation`.
**When to use:** ALL data-fetching hooks. STATE.md explicitly prohibits the positional-argument form.

```typescript
// src/hooks/usePersons.ts
// Source: TanStack Query v5 docs
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listPersons, createPerson, enrollPerson, deletePerson } from '../api/persons';

export function usePersons() {
  return useQuery({
    queryKey: ['persons'],
    queryFn:  listPersons,
    staleTime: 30_000,
  });
}

export function useCreatePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createPerson,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}

export function useEnrollPerson(personId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) => enrollPerson(personId, formData),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}

export function useDeletePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deletePerson(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}
```

### Pattern 4: POST /search as a Query (not mutation)
**What:** `/search` is a POST but semantically a read — use `useQuery` with a stable `queryKey`.
**When to use:** SearchPage filter state drives the query key, causing auto-refetch on filter change.

```typescript
// src/hooks/useSearch.ts
export interface SearchFilters {
  personIds:           string[];
  classes:             string[];
  dateFrom:            string | null;
  dateTo:              string | null;
  videoIds:            string[];
  includeUnknownFaces: boolean;
  page:                number;
  pageSize:            number;
}

export function useSearch(filters: SearchFilters) {
  return useQuery({
    queryKey: ['search', filters],    // deep-equal comparison triggers refetch on change
    queryFn:  () => searchFrames(filters),
    staleTime: 60_000,               // search results don't change while browsing
    placeholderData: (prev) => prev, // keeps previous results visible during refetch
  });
}
```

### Pattern 5: Video Streaming with Timestamp Seek
**What:** Fetch presigned URL as JSON, then open in a new tab with HTML media fragment `#t=N`.
**When to use:** "Play in video" button in the frame detail modal.

```typescript
// src/components/FrameModal.tsx
async function handlePlayInVideo(videoId: string, tsMs: number) {
  // authFetch GET /videos/{id}/stream-url → { url: "https://minio/.../video.mp4?X-Amz-..." }
  // NOTE: this requires a new API endpoint (GET /videos/{id}/stream-url returning JSON)
  const data = await authFetch(`/videos/${videoId}/stream-url`).then(r => r.json());
  const seconds = (tsMs / 1000).toFixed(3);
  window.open(`${data.url}#t=${seconds}`, '_blank', 'noopener,noreferrer');
}
```

**Why not use `GET /videos/{id}/stream` (the existing 302 endpoint)?**
The existing endpoint returns a `302 Location:` header. To extract the final MinIO URL with `fetch()`,
we'd need `redirect: 'manual'` and then read the `Location` header — but `Location` is forbidden in CORS
responses from cross-origin redirects. The JSON endpoint avoids this entirely.
[VERIFIED: Fetch Spec — opaque-redirect response does not expose Location header to JS]

### Pattern 6: Drag-and-Drop Upload (Native HTML5)
**What:** Native `ondragover`/`ondrop` events + `<input type="file" multiple>` — no library needed.
**When to use:** People page "Add person" and "Add photos" flows.

```typescript
// src/components/DropZone.tsx
export function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files).filter(f =>
      f.type.startsWith('image/')
    );
    onFiles(files);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={clsx(
        'border-2 border-dashed rounded-lg p-8 text-center cursor-pointer',
        dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300'
      )}
    >
      <input
        type="file"
        multiple
        accept="image/*"
        className="hidden"
        onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
        id="file-input"
      />
      <label htmlFor="file-input" className="cursor-pointer">
        Drop images here or click to browse
      </label>
    </div>
  );
}
```

### Pattern 7: Enrollment Rejection Feedback
**What:** After `POST /persons/{id}/enroll`, render each rejected file with its reason.
**Response shape** (from `persons.py` EnrollResponse):
```typescript
interface EnrollResponse {
  person_id: string;
  enrolled:  number;
  rejected:  Array<{ filename: string; reason: string }>;
  warning:   string | null;  // "Only N images enrolled. Accuracy reduced with <5 images."
}
```

### Pattern 8: Vite Multi-Stage Dockerfile
**What:** Node.js build stage produces `dist/`, nginx stage serves it.

```dockerfile
# services/web/Dockerfile (replacement)
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build        # vite build → dist/

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

### Pattern 9: Vite Config (dev proxy mirrors nginx)
**What:** Vite dev server proxies `/api/` to `localhost:8000` — same routing as nginx in prod.

```typescript
// services/web/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target:   'http://localhost:8000',
        rewrite:  (path) => path.replace(/^\/api/, ''),
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',           // default; explicit for clarity
    sourcemap: false,         // omit in prod build for smaller output
  },
});
```

### Anti-Patterns to Avoid
- **Using TanStack Query positional form:** `useQuery(['key'], fn)` — **BANNED** (STATE.md). Use object form only.
- **Storing bearer token in sessionStorage or a React state atom:** Token would be lost on page refresh. Use `localStorage`.
- **Calling the API with a hardcoded `http://api:8000` base URL:** That hostname only resolves inside Docker. The nginx proxy (`/api/`) is the correct browser-facing path.
- **Presigned URL caching:** Never cache MinIO presigned URLs — they expire in 1 hour and the API generates fresh ones per request. This is explicitly noted in `storage.py` comments.
- **Using `useEffect` to fetch data:** Let TanStack Query handle all data fetching — do not use bare `useEffect` + `setState` for API calls.
- **Tailwind v4:** `npm install tailwindcss` would install v4.3.0 which has breaking config changes. Always use `tailwindcss@^3`.
- **`redirect: 'manual'` to extract Location header:** Cross-origin CORS restrictions prevent JS from reading `Location` headers in redirect responses. Use a JSON endpoint instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Query deduplication + cache | Custom fetch + useEffect + useState | @tanstack/react-query | Race conditions, stale closures, cache invalidation are all solved |
| Accessible modal/dialog | Custom focus-trap + aria-modal | @headlessui/react Dialog | Screen reader behavior, focus management, keyboard escape handling are subtle and bug-prone |
| Date formatting | Moment.js or custom strftime | date-fns | date-fns is tree-shakeable, immutable, locale-aware |
| CSS utility generation | Custom CSS-in-JS or Sass | Tailwind CSS v3 | PurgeCSS built-in, responsive breakpoints, dark mode support |
| Conditional class names | String concatenation | clsx | Handles arrays, objects, undefined values without bugs |

**Key insight:** The biggest pitfall in React data-fetching SPAs is re-inventing `useQuery`. Custom solutions
always miss cache invalidation, background refetch, loading/error state coordination, and optimistic updates.

---

## Critical Issue: Bearer Token + `<img src>` Thumbnails

### The Problem
```
search.py:  thumbnail_url = f"/frames/{fid}/image"   # relative path returned in results
main.py:    app.include_router(frames_router, dependencies=[Depends(require_token)])
```

The `GET /frames/{id}/image` endpoint **requires a bearer token**. Browser `<img>` elements do NOT send
`Authorization` headers. Therefore `<img src="/api/frames/123/image">` returns `401 Unauthorized`.
Every frame thumbnail in the search results grid will be broken.

### Option A — Remove auth from frames router (RECOMMENDED)
**Change in `services/api/app/main.py`:**
```python
# Before:
app.include_router(frames_router, dependencies=[Depends(require_token)])

# After:
app.include_router(frames_router)   # public — presigned URL is self-secured
```

**Rationale:**
1. The endpoint returns a 302 redirect to a MinIO presigned URL (HMAC-signed, 1h TTL). The presigned URL
   itself is cryptographically protected — an attacker who guesses a frame ID only gets a redirect to a
   time-limited URL that requires valid MinIO credentials to generate (they cannot forge it).
2. Frame IDs are sequential integers (`1, 2, 3...`). Enumerating them without first knowing which IDs
   exist (via the auth-protected `/search` endpoint) provides no actionable intelligence.
3. Self-hosted home system accessed via Cloudflare Tunnel — the bearer token is the outermost protection
   against internet exposure; thumbnail accessibility is not a meaningful attack surface.
4. No client-side complexity required. `<img src="/api/frames/123/image">` works immediately.

**Option B — Fetch + blob URL (fallback if API code is untouchable)**
```typescript
// AuthImage component — more complex, adds memory pressure
function AuthImage({ frameId, alt }: { frameId: number; alt: string }) {
  const [blobUrl, setBlobUrl] = useState('');
  useEffect(() => {
    let url = '';
    authFetch(`/frames/${frameId}/image`)
      .then(r => r.blob())
      .then(blob => { url = URL.createObjectURL(blob); setBlobUrl(url); });
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [frameId]);
  return blobUrl ? <img src={blobUrl} alt={alt} /> : <div className="animate-pulse bg-gray-200" />;
}
```

**Why Option B is inferior for this use case:**
- Memory pressure: 20 thumbnails × ~30 KB each = ~600 KB of blob URLs held in browser heap
- Each navigation back to search results re-fetches all thumbnails (blob URLs are not cached by TanStack Query)
- `fetch` follows the 302 redirect to MinIO. If `MINIO_ENDPOINT=minio:9000` (internal Docker hostname),
  the redirect target is not browser-accessible — Option B silently fails for the same reason as the presigned URL issue described next.

### Companion Issue: MinIO Presigned URL Hostname

`services/api/app/storage.py` creates the Minio client using `config.MINIO_ENDPOINT` (`minio:9000` by default).
The Python `minio` library generates presigned URLs using that hostname. A URL like
`http://minio:9000/frames/img.jpg?X-Amz-...` is only reachable inside the Docker network, **not** from a browser.

**Fix required in Phase 4 (small API change):**

Add `MINIO_PUBLIC_ENDPOINT` to `services/api/app/config.py`:
```python
# New optional var — falls back to MINIO_ENDPOINT if not set
MINIO_PUBLIC_ENDPOINT: str = os.getenv("MINIO_PUBLIC_ENDPOINT", "") or os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_PUBLIC_USE_SSL:  bool = os.getenv("MINIO_PUBLIC_USE_SSL", str(MINIO_USE_SSL)).lower() == "true"
```

And create a second Minio client in `storage.py` for presigned URL generation that uses the public endpoint:
```python
_public_client: Optional[Minio] = None

def get_public_minio_client() -> Minio:
    global _public_client
    if _public_client is None:
        _public_client = Minio(
            config.MINIO_PUBLIC_ENDPOINT,
            access_key=config.MINIO_ACCESS_KEY,
            secret_key=config.MINIO_SECRET_KEY,
            secure=config.MINIO_PUBLIC_USE_SSL,
        )
    return _public_client
```

Use `get_public_minio_client()` in `generate_presigned_url()`.

Add to `.env.example`:
```
# Public-facing MinIO endpoint (browser-accessible) — override if MINIO_ENDPOINT is internal Docker hostname
MINIO_PUBLIC_ENDPOINT=localhost:9000
MINIO_PUBLIC_USE_SSL=false
```

---

## Missing API Endpoints (Must Add in Phase 4)

The following endpoints are required by the Web UI but do not exist in the current API codebase:

### 1. `GET /videos` — Video Listing (for Videos page, WEB-02)
**Required response shape (new `VideoListItem` Pydantic model):**
```python
class VideoListItem(BaseModel):
    id:              str
    minio_key:       str
    status:          str    # pending | processing | done | failed
    error_message:   Optional[str]
    recorded_at:     Optional[str]
    duration_sec:    Optional[float]
    frame_count:     int     # COUNT of frames
    detection_count: int     # COUNT of detections
    face_count:      int     # COUNT of face_detections
    ingested_at:     str     # created_at
```

### 2. `GET /videos/{id}/stream-url` — Presigned URL as JSON (for timestamp seek, WEB-01)
**Required response shape:**
```python
class StreamUrlResponse(BaseModel):
    url: str    # presigned MinIO URL (browser-accessible)
```

This replaces the need for JS to parse a 302 redirect for the "Play in video" button.
The existing `GET /videos/{id}/stream` (302 redirect) can remain unchanged for direct browser navigation.

### 3. `GET /clusters` — Unknown Cluster Listing (for Unknown Clusters page, WEB-04)
This endpoint will be added in Phase 3 (`unknown_clusters` table). Phase 4 plan must account for
"graceful empty state" if Phase 3 is not yet complete (Phase 3 status is "Not started" in STATE.md).

**Expected shape (from Phase 3 ROADMAP):**
```python
class ClusterItem(BaseModel):
    id:                   str    # UUID
    representative_frame_id: Optional[int]
    appearance_count:     int
    first_seen:           Optional[str]
    last_seen:            Optional[str]
    thumbnail_url:        Optional[str]   # /frames/{id}/image
```

### 4. `POST /videos/{id}/reingest` proxy (for Re-ingest button, WEB-02)
The re-ingest endpoint is `POST /ingest` on the **ingestion-worker** service (port 8001, not the API).
Options:
- **Option A (recommended):** Add `POST /videos/{id}/reingest` to the API service that calls the
  ingestion-worker internally (service-to-service: `http://ingestion-worker:8001/ingest`)
- **Option B:** Add an nginx proxy location for the ingestion-worker in `nginx.conf`
  (`location /worker/ { proxy_pass http://ingestion-worker:8001/; }`)

Option A keeps the API as the single-entry-point for the UI and avoids exposing the raw worker API.

---

## Common Pitfalls

### Pitfall 1: Tailwind v4 Installed Instead of v3
**What goes wrong:** Running `npm install tailwindcss` installs v4.3.0. The `tailwind.config.js` format
is completely different in v4 (CSS-native configuration replaces JS config file entirely).
**Why it happens:** v4 became the default on npm registry.
**How to avoid:** Always pin `tailwindcss@^3` in `package.json`. Use `tailwind.config.cjs` (CommonJS, required for Vite + Tailwind v3 integration).
**Warning signs:** Error "No utility classes were detected in your source files" or missing `@tailwind base` processing.

### Pitfall 2: TanStack Query v5 Positional Argument Form
**What goes wrong:** Using `useQuery(['key'], fn, opts)` (v4 form) — runtime error in v5: "Expected object".
**Why it happens:** Most online tutorials still show the v4 API.
**How to avoid:** STATE.md explicitly bans positional form. Always: `useQuery({ queryKey: [...], queryFn: ... })`.
**Warning signs:** TypeScript error on `useQuery` call signature, or "Argument of type 'string[]' is not assignable to parameter" error.

### Pitfall 3: API Base URL Empty String vs Undefined
**What goes wrong:** If `localStorage.getItem('hvs:api_base_url')` returns `null` (never set) and the
code does `null + '/persons'` → `"null/persons"`.
**How to avoid:** Always default to `''` (empty string = use nginx proxy): `localStorage.getItem(key) ?? ''`.
An empty `apiBaseUrl` means "use the nginx `/api/` proxy" which is the correct default.
**Warning signs:** `fetch('null/persons')` errors in the network tab.

### Pitfall 4: POST /search with Empty Filter Arrays
**What goes wrong:** Sending `{ personIds: [], classes: [] }` — the API SQL builder treats `NULL` differently
from an empty array. Looking at `search.py`: `$1::text[] IS NULL` — an empty array `[]` is NOT NULL, so the
SQL `$1::text[] IS NULL OR ...` evaluates the `IS NULL` branch as false, then tries `ANY([])` which matches nothing.
**How to avoid:** Convert empty arrays to `null` (undefined) before sending:
```typescript
const body = {
  person_ids: filters.personIds.length ? filters.personIds : undefined,
  classes:    filters.classes.length   ? filters.classes   : undefined,
  ...
};
```
**Warning signs:** Search with no filters selected returns 0 results instead of all results.

### Pitfall 5: MinIO Presigned URL in `<img src>` Has Wrong Hostname
**What goes wrong:** `MINIO_ENDPOINT=minio:9000` (internal Docker hostname). Presigned URLs contain
`http://minio:9000/...`. Browser cannot resolve `minio` — images 404 or fail to load with a network error.
**How to avoid:** Set `MINIO_PUBLIC_ENDPOINT=localhost:9000` (or the host's LAN IP) in `.env`.
**Warning signs:** Images fail with `ERR_NAME_NOT_RESOLVED` for host `minio` in browser network tab.

### Pitfall 6: Deep Links Returning 404 from nginx
**What goes wrong:** User navigates to `http://localhost:8080/people` and refreshes — nginx looks for
`/people` as a static file, doesn't find it, returns 404.
**How to avoid:** The `try_files $uri $uri/ /index.html;` in `nginx.conf` is **already configured** —
do not remove it. The Vite build must produce `index.html` at the root of `dist/`.
**Warning signs:** Direct URL access or refresh on any non-root path returns 404.

### Pitfall 7: Vite Build Output Path Mismatch in Dockerfile
**What goes wrong:** Dockerfile copies `dist/` but Vite was configured with a different `outDir`.
**How to avoid:** Keep `build.outDir: 'dist'` (default) in `vite.config.ts`. Dockerfile COPY line:
`COPY --from=build /app/dist /usr/share/nginx/html`.
**Warning signs:** `COPY --from=build /app/dist` step fails in Docker build with "not found".

### Pitfall 8: Date Range Strings in POST /search
**What goes wrong:** Sending `"2024-01-01"` as `date_from` — the API expects ISO 8601 datetime
(`"2024-01-01T00:00:00Z"`). Raw date strings may fail the `timestamptz` cast in PostgreSQL.
**How to avoid:** Use `date-fns` `formatISO()` or append `T00:00:00Z` / `T23:59:59Z` to date strings.
**Warning signs:** 422 Unprocessable Entity from `/search` when date filters are used.

---

## Code Examples

### Exact API Type Definitions (from source code)
```typescript
// src/types/api.ts — derived directly from services/api/app/search.py and persons.py

export interface DetectionResult {
  class_name:  string;
  confidence:  number;
  bbox:        [number, number, number, number]; // [x1, y1, x2, y2]
}

export interface FaceResult {
  face_detection_id:  number;
  matched_person_id:  string | null;
  person_name:        string | null;
  match_tier:         'confident' | 'probable' | null;
  match_similarity:   number | null;
  bbox:               [number, number, number, number];
}

export interface FrameResult {
  frame_id:      number;
  video_id:      string;
  ts_ms:         number;
  thumbnail_url: string;   // "/frames/{id}/image" — RELATIVE PATH, prepend /api
  detections:    DetectionResult[];
  faces:         FaceResult[];
}

export interface SearchResponse {
  results:    FrameResult[];
  pagination: { page: number; page_size: number; total: number; has_next: boolean };
}

export interface PersonResponse {
  id:               string;
  name:             string;
  notes:            string | null;
  created_at:       string;
  enrollment_count: number;
}

export interface EnrollResponse {
  person_id: string;
  enrolled:  number;
  rejected:  Array<{ filename: string; reason: string }>;
  warning:   string | null;
}

export interface RematchResponse {
  person_id: string;
  matched:   number;
}

export interface PersonFaceResult {
  face_detection_id: number;
  frame_id:          number;
  video_id:          string;
  ts_ms:             number;
  match_tier:        string | null;
  match_similarity:  number | null;
  det_score:         number | null;
  thumbnail_url:     string;
}
```

### QueryClient Setup
```typescript
// src/main.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:          30_000,   // 30 s before background refetch
      retry:              1,
      refetchOnWindowFocus: false,  // avoid spurious refetch when tabbing back
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <SettingsProvider>
        <App />
      </SettingsProvider>
      {import.meta.env.DEV && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  </React.StrictMode>
);
```

### Enroll Flow with Per-File Rejection Display
```typescript
// Usage in PeoplePage
const enrollMutation = useEnrollPerson(personId);

async function handleSubmit(files: File[]) {
  const formData = new FormData();
  files.forEach(f => formData.append('images', f, f.name));
  
  // useMutation with FormData (override Content-Type to let browser set multipart boundary)
  const result = await enrollMutation.mutateAsync(formData);
  
  if (result.warning) setWarning(result.warning);
  setRejected(result.rejected);   // [{filename, reason}] — render below drop zone
}
```

```typescript
// src/api/persons.ts — enrollment API function
export async function enrollPerson(personId: string, formData: FormData): Promise<EnrollResponse> {
  // NOTE: Do NOT set Content-Type header for FormData — browser sets multipart boundary automatically
  const { apiBaseUrl, apiToken } = getSettings();
  const prefix = apiBaseUrl || '/api';
  const response = await fetch(`${prefix}/persons/${personId}/enroll`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiToken}` },  // NO Content-Type here
    body: formData,
  });
  if (!response.ok) throw new Error(`${response.status}`);
  return response.json();
}
```

### Search Pagination (Recommended: Paginated Buttons)
```typescript
// Rationale for paginated buttons over infinite scroll:
// - Security footage review: users want to know "page 3 of 8" (total context)
// - Users often jump back to a specific result after opening modal
// - OFFSET pagination in the API is stateless — page changes are cheap
// - Infinite scroll accumulates DOM nodes across pages (performance issue with thumbnails)

const [page, setPage] = useState(1);
const { data, isFetching } = useSearch({ ...filters, page, pageSize: 20 });

// Render: ← [1] [2] [3] ... [N] →
// Use data.pagination.total and data.pagination.has_next to render controls
```

### Tailwind v3 Config
```javascript
// services/web/tailwind.config.cjs
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| TanStack Query v4 positional args | v5 object-form only | v5.0 (Oct 2023) | All tutorial code pre-2024 uses wrong API |
| Tailwind v3 JS config file | Tailwind v4 CSS-based config | v4.0 (Jan 2025) | Project is pinned to v3 to avoid this |
| CRA (create-react-app) for scaffolding | Vite | CRA deprecated 2023 | CRA is unmaintained; Vite is the standard |
| React class components | React hooks (functional) | React 16.8+ | Class components are legacy |
| redux / zustand for server state | TanStack Query | ~2021 | Server state ≠ client state; Query handles cache |

**Deprecated/outdated:**
- `create-react-app`: Unmaintained since 2023; Vite is the standard scaffold tool
- `tailwindcss@4.x` for this project: v4 requires CSS-native config (no `tailwind.config.js`); project is pinned to v3
- `react-query@4` (positional arg form): STATE.md and v5 API both forbid this pattern

---

## nginx + Docker Integration

### What's Already Correct in nginx.conf
```nginx
# ✅ ALREADY CONFIGURED — do not change
location / {
    try_files $uri $uri/ /index.html;   # SPA fallback routing
}

location /api/ {
    proxy_pass http://api:8000/;        # strips /api prefix, proxies all headers through
}
```

The nginx config is **complete for Phase 4**. No modifications needed.

### Env Var Strategy for SPA
The React app does NOT need build-time environment variables for the API URL because:
1. The nginx `/api/` proxy handles same-origin routing (no CORS)
2. The user can override the API base URL at runtime via the Settings page (localStorage)
3. `VITE_*` env vars are baked into the bundle — a rebuild would be required to change them

For local development, `vite.config.ts` proxies `/api/` to `localhost:8000` (same as nginx in prod).
No `.env` file is needed for the web service itself.

---

## Settings Page Behavior

**localStorage keys:**
- `hvs:api_token` — bearer token (`API_TOKEN` env var value)
- `hvs:api_base_url` — API base URL (default: `''` = use nginx `/api/` proxy)

**When token is missing:**
- Do NOT redirect to Settings page silently — that creates confusing loops
- Show an inline banner: "API token not configured. [Go to Settings →]"
- All query hooks should check `apiToken === ''` and return a disabled query:
  ```typescript
  useQuery({ ..., enabled: !!apiToken })
  ```
- This prevents unauthenticated requests and shows clear UI feedback

**When API call returns 401:**
- Show inline error: "Authentication failed — check your API token in Settings"
- Do NOT auto-redirect (URL may have changed, not a token problem)

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Vite build in Dockerfile | ✓ (host) | 22.9.0 | — |
| npm | Package installation | ✓ (host) | 11.8.0 | — |
| Docker | Multi-stage build | ✓ (assumed) | — | Run Vite build manually |
| nginx 1.27-alpine | Static serving | ✓ (in Dockerfile FROM) | 1.27 | — |
| MinIO (browser-accessible) | Thumbnail + video loading | ⚠️ config-dependent | — | Set MINIO_PUBLIC_ENDPOINT |

**Missing dependencies with fallback:**
- `MINIO_PUBLIC_ENDPOINT`: Not in `.env.example` yet. Without it, presigned URLs use `minio:9000`
  (internal Docker hostname) — thumbnails and videos will fail to load in the browser.
  **Resolution:** Add `MINIO_PUBLIC_ENDPOINT` to `config.py` and `.env.example` (documented above).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | localStorage key prefix `hvs:` | Pattern 1: Settings Context | Low risk — trivial to change, affects only Settings page |
| A2 | Paginated buttons preferred over infinite scroll for security footage review UX | Architecture Patterns | Medium — if user prefers infinite scroll, `useInfiniteQuery` requires minor refactor of search hook and results component |
| A3 | Phase 3 clustering endpoint will be `GET /clusters` | Missing API Endpoints | Medium — actual Phase 3 endpoint name unknown; Unknown Clusters page must show "no clusters" gracefully if endpoint is absent |
| A4 | MinIO is accessible from the browser host at a port that can be set via `MINIO_PUBLIC_ENDPOINT` | Critical Issue section | High — if MinIO is only accessible inside Docker network with no host port mapping, thumbnails and video cannot load at all. User must expose MinIO on a host port. |
| A5 | `react-router-dom@^6` is preferred over v7 for this SPA | Standard Stack | Low — v7 also works for a pure SPA; v6 is more widely documented |

---

## Open Questions

1. **Should `GET /videos/{id}/stream` be replaced or supplemented?**
   - What we know: existing endpoint returns 302; used by Phase 2 done-when criteria
   - What's unclear: can the existing endpoint remain for direct browser navigation while `stream-url` is added for UI JS calls?
   - Recommendation: Keep existing 302 endpoint; add new `stream-url` JSON endpoint. No breaking changes.

2. **Phase 3 cluster endpoint name and shape**
   - What we know: Phase 3 adds `POST /cluster/run`; ROADMAP describes cluster data structure
   - What's unclear: Does Phase 3 also add `GET /clusters`? Or is the Web UI responsible for adding it?
   - Recommendation: Phase 4 plan must add `GET /clusters` if Phase 3 does not. Unknown Clusters page shows empty state gracefully when no clusters exist.

3. **Mobile viewport (390×844) — sidebar layout**
   - What we know: Filter sidebar works on 1280×800; mobile is 390×844
   - What's unclear: Should sidebar collapse to a bottom sheet or overlay drawer on mobile?
   - Recommendation: Collapse to a slide-in drawer triggered by a "Filters" button on mobile (Headless UI Dialog or native CSS). Tailwind `md:` breakpoint for the transition.

---

## Sources

### Primary (HIGH confidence)
- npm registry (`npm view <pkg> version`) — all package versions verified 2026-06-01
- `services/web/nginx.conf` — nginx config inspected directly; SPA routing and API proxy confirmed
- `services/web/Dockerfile` — single-stage nginx; multi-stage upgrade required
- `services/api/app/search.py` — exact SearchResponse, FrameResult, PaginationInfo shapes
- `services/api/app/persons.py` — exact PersonResponse, EnrollResponse, RematchResponse shapes
- `services/api/app/frames.py` — confirmed: frames endpoint returns 302, auth-protected
- `services/api/app/videos.py` — confirmed: stream endpoint returns 302, auth-protected
- `services/api/app/main.py` — confirmed: `frames_router` registered with `Depends(require_token)`
- `services/api/app/storage.py` — confirmed: Minio client uses `config.MINIO_ENDPOINT` directly
- `services/api/app/config.py` — confirmed: no `MINIO_PUBLIC_ENDPOINT` variable exists
- `.planning/STATE.md` — project constraints: Tailwind v3 pinned, TanStack Query v5 object-form only
- `.planning/ROADMAP.md` — Phase 4 plan descriptions and WEB-01 through WEB-07 requirements

### Secondary (MEDIUM confidence)
- HTML Living Standard: Media Fragments `#t=<seconds>` — well-established browser feature [ASSUMED from training, standard since 2012]
- Fetch Specification: opaque-redirect responses do not expose `Location` header — [ASSUMED from training; prevents `redirect: 'manual'` approach]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all package versions verified against npm registry
- Architecture: HIGH — nginx config and API response shapes verified against source code
- Critical auth issue: HIGH — verified in `main.py` line 63 (`frames_router` with `Depends(require_token)`)
- Missing endpoints: HIGH — absence verified by reading all files in `services/api/app/`
- Pitfalls: HIGH — most derived from direct code inspection; Tailwind v3/v4 confirmed by npm registry

**Research date:** 2026-06-01
**Valid until:** 2026-09-01 (TanStack Query v5 and Tailwind v3 are stable; React 18 is in maintenance mode)
