# Phase 3: Unknown Face Intelligence & Telegram Digest — Pattern Map

**Mapped:** 2025-07
**Files analyzed:** 12 (new/modified)
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/api/app/clustering.py` | service + router | CRUD + batch | `services/api/app/persons.py` | role-match (same router pattern, asyncpg bulk UPDATE) |
| `services/api/app/digest.py` | service + router | event-driven + file-I/O | `services/api/app/persons.py` + `services/api/app/storage.py` | partial (same router skeleton; MinIO fetch pattern from storage.py) |
| `db/migrations/003_add_cluster_state_cols.sql` | migration | — | `db/migrations/002_add_notes_to_known_persons.sql` | exact |
| `services/api/app/main.py` (modify) | config | — | `services/api/app/main.py` | self (add two include_router lines) |
| `services/api/app/config.py` (modify) | config | — | `services/api/app/config.py` | self (add 3 env vars following exact existing pattern) |
| `services/api/requirements.txt` (verify) | config | — | — | no-op (all deps already present) |
| `services/web/src/api/clusters.ts` (modify) | hook | request-response | `services/web/src/api/persons.ts` | exact (same useMutation + invalidateQueries pattern) |
| `services/web/src/types/api.ts` (modify) | type | — | `services/web/src/types/api.ts` | self (extend existing `ClusterItem` interface) |
| `services/web/src/pages/ClustersPage.tsx` (modify) | component/page | request-response | `services/web/src/pages/PeoplePage.tsx` | role-match (same section/grid layout, loading/error states) |
| `services/web/src/components/ClusterCard.tsx` (modify) | component | request-response | `services/web/src/components/ClusterCard.tsx` | self (change submit action only) |
| `.env.example` (modify) | config | — | `.env.example` | self (append 2 vars under Telegram section) |
| `docs/n8n-clustering-workflow.json` | config/doc | — | — | no analog |

---

## Pattern Assignments

---

### `services/api/app/clustering.py` (service + router, CRUD + batch)

**Analog:** `services/api/app/persons.py`

**Imports pattern** (persons.py lines 1–21):
```python
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from . import config
from .db import get_pool
from .storage import get_minio_client   # add for MinIO byte fetch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clusters", tags=["clusters"])
# NOTE: POST /cluster/run uses prefix="/cluster" (no 's') — declare a second router
cluster_run_router = APIRouter(prefix="/cluster", tags=["clustering"])
```

**Auth pattern** — applied at main.py registration level, NOT per-endpoint (persons.py pattern):
```python
# In main.py (not in the router file itself):
app.include_router(clustering_router, dependencies=[Depends(require_token)])
app.include_router(cluster_run_router, dependencies=[Depends(require_token)])
```

**Core router pattern — GET endpoint with asyncpg JOIN** (persons.py lines 90–118 adapted):
```python
class ClusterResponse(BaseModel):
    id:                      str
    representative_frame_id: Optional[int]
    appearance_count:        int
    first_seen:              Optional[str]
    last_seen:               Optional[str]
    thumbnail_url:           Optional[str]
    ignored:                 bool

@router.get("", response_model=list[ClusterResponse])
async def list_clusters(include_ignored: bool = False) -> list[ClusterResponse]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                uc.id::text,
                uc.appearance_count,
                uc.first_seen::text,
                uc.last_seen::text,
                uc.ignored,
                fd.frame_id AS representative_frame_id
            FROM unknown_clusters uc
            LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id
            WHERE uc.promoted_at IS NULL
              AND ($1 = true OR uc.ignored = false)
            ORDER BY uc.appearance_count DESC
        """, include_ignored)
    return [
        ClusterResponse(
            id=r["id"],
            representative_frame_id=r["representative_frame_id"],
            appearance_count=r["appearance_count"],
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
            thumbnail_url=f"/frames/{r['representative_frame_id']}/image" if r["representative_frame_id"] else None,
            ignored=r["ignored"],
        )
        for r in rows
    ]
```

**Core pattern — PATCH/state-change endpoints** (persons.py lines 250–263 adapted):
```python
@router.post("/{cluster_id}/ignore", status_code=status.HTTP_200_OK)
async def ignore_cluster(cluster_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET ignored = true WHERE id = $1", cluster_id
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "ignored": True}

@router.delete("/{cluster_id}/ignore", status_code=status.HTTP_200_OK)
async def restore_cluster(cluster_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET ignored = false WHERE id = $1", cluster_id
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "ignored": False}
```

**Core pattern — promote endpoint** (persons.py rematch bulk UPDATE, lines 334–349 adapted):
```python
@router.post("/{cluster_id}/promote", status_code=status.HTTP_200_OK)
async def promote_cluster(cluster_id: UUID, person_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Bulk update all member face_detections
        result = await conn.execute("""
            UPDATE face_detections
            SET matched_person_id = $1::uuid,
                match_tier        = 'confident',
                match_similarity  = 1.0
            WHERE unknown_cluster_id = $2::uuid
              AND matched_person_id IS NULL
        """, person_id, cluster_id)
        # Mark cluster as promoted (disappears from GET /clusters)
        await conn.execute(
            "UPDATE unknown_clusters SET promoted_at = now() WHERE id = $1::uuid",
            cluster_id,
        )
    matched = int(result.split()[-1])  # "UPDATE N" → N
    logger.info("Promoted cluster %s → person %s (%d faces)", cluster_id, person_id, matched)
    return {"cluster_id": str(cluster_id), "person_id": str(person_id), "matched": matched}
```

**Core pattern — POST /cluster/run** (persons.py rematch structure + HDBSCAN from RESEARCH.md):
```python
class ClusterRunResponse(BaseModel):
    clusters_created: int
    clusters_updated: int
    faces_assigned:   int

@cluster_run_router.post("/run", response_model=ClusterRunResponse)
async def run_clustering() -> ClusterRunResponse:
    """Run HDBSCAN on all unmatched face embeddings. Idempotent."""
    pool = await get_pool()
    minio_client = get_minio_client()

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, normed_embedding, unknown_cluster_id::text
            FROM face_detections
            WHERE matched_person_id IS NULL
              AND normed_embedding IS NOT NULL
        """)

    if len(rows) < config.CLUSTER_MIN_SIZE:
        return ClusterRunResponse(clusters_created=0, clusters_updated=0, faces_assigned=0)

    # ... HDBSCAN fit + stable UUID mapping + upsert (see RESEARCH.md Pattern 1)
    # executemany pattern copied from persons.py lines 215–224
```

**Error handling pattern** (persons.py lines 72–78 — unique constraint + generic re-raise):
```python
try:
    await conn.execute(...)
except Exception as exc:
    if "unique" in str(exc).lower():
        raise HTTPException(status_code=409, detail="...")
    raise
```

**Bulk UPDATE pattern** (persons.py lines 334–349 — executemany):
```python
await conn.executemany(
    "UPDATE face_detections SET unknown_cluster_id = $1::uuid WHERE id = $2",
    [(cluster_uuid, face_id) for face_id, cluster_uuid in assignments],
)
```

---

### `services/api/app/digest.py` (service + router, event-driven + file-I/O)

**Analog:** `services/api/app/persons.py` (router skeleton) + `services/api/app/storage.py` (MinIO pattern)

**Imports pattern**:
```python
import asyncio
import logging
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, status
from pydantic import BaseModel
from telegram import Bot, InputMediaPhoto
from telegram.error import TelegramError

from . import config
from .db import get_pool
from .storage import get_minio_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/digest", tags=["digest"])
```

**Router registration** (follows main.py pattern — protected):
```python
# In main.py:
from .digest import router as digest_router
app.include_router(digest_router, dependencies=[Depends(require_token)])
```

**Core endpoint pattern** (persons.py router post structure):
```python
class DigestResponse(BaseModel):
    sent:    int
    skipped: bool
    message: Optional[str] = None

@router.post("/send", response_model=DigestResponse)
async def send_digest() -> DigestResponse:
    """Send unknown cluster thumbnails to Telegram via sendMediaGroup."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram not configured: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing",
        )
    pool = await get_pool()
    minio_client = get_minio_client()

    async with pool.acquire() as conn:
        clusters = await conn.fetch("""
            SELECT
                uc.id::text,
                uc.appearance_count,
                uc.first_seen::text,
                uc.last_seen::text,
                f.minio_key
            FROM unknown_clusters uc
            LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id
            LEFT JOIN frames f ON f.id = fd.frame_id
            WHERE uc.ignored = false
              AND uc.promoted_at IS NULL
              AND f.minio_key IS NOT NULL
            ORDER BY uc.appearance_count DESC
            LIMIT 10
        """)

    if not clusters:
        return DigestResponse(sent=0, skipped=True, message="No active clusters")

    # ... build media_group, call bot.send_media_group (see RESEARCH.md Pattern 6)
```

**MinIO byte-fetch pattern** (storage.py lines 24–35 adapted for internal byte download):
```python
# Use get_minio_client() (internal endpoint, not public) for internal byte fetch
# Run synchronous minio.get_object() in thread pool to avoid blocking event loop
loop = asyncio.get_event_loop()
response = await loop.run_in_executor(
    None, lambda: minio_client.get_object(config.MINIO_BUCKET_FRAMES, minio_key)
)
img_bytes = response.read()
response.close()
response.release_conn()
```

**Error handling** (persons.py error pattern — log + continue rather than abort all):
```python
try:
    response = await loop.run_in_executor(...)
    img_bytes = response.read()
    response.close()
    response.release_conn()
except Exception as e:
    logger.warning("Could not fetch frame for cluster %s: %s", cluster["id"], e)
    continue   # skip this cluster, send the rest
```

---

### `db/migrations/003_add_cluster_state_cols.sql` (migration)

**Analog:** `db/migrations/002_add_notes_to_known_persons.sql`

**Full pattern** (002 migration, all 4 lines):
```sql
-- Phase 2 migration: add optional notes field to known_persons.
-- Safe to run multiple times (IF NOT EXISTS guard).
ALTER TABLE known_persons
    ADD COLUMN IF NOT EXISTS notes TEXT;
```

**Apply exactly this pattern** — header comment + `IF NOT EXISTS` guards + index:
```sql
-- Phase 3 migration: add ignored + promoted_at state columns to unknown_clusters.
-- Safe to run multiple times (IF NOT EXISTS guard on both ADD COLUMN and CREATE INDEX).
ALTER TABLE unknown_clusters
    ADD COLUMN IF NOT EXISTS ignored     BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS unknown_clusters_ignored_idx ON unknown_clusters (ignored);
```

---

### `services/api/app/main.py` (modify — add two router registrations)

**Analog:** `services/api/app/main.py` (self — lines 56–63)

**Existing pattern to copy** (main.py lines 56–63):
```python
app.include_router(persons_router, dependencies=[Depends(require_token)])

from .search import router as search_router
from .videos import router as videos_router
from .frames import router as frames_router

app.include_router(search_router,  dependencies=[Depends(require_token)])
app.include_router(videos_router,  dependencies=[Depends(require_token)])
app.include_router(frames_router)   # public
```

**New lines to add** (append after existing includes, same style):
```python
from .clustering import router as clustering_router
from .clustering import cluster_run_router
from .digest     import router as digest_router

app.include_router(clustering_router, dependencies=[Depends(require_token)])
app.include_router(cluster_run_router, dependencies=[Depends(require_token)])
app.include_router(digest_router,     dependencies=[Depends(require_token)])
```

---

### `services/api/app/config.py` (modify — add 3 env vars)

**Analog:** `services/api/app/config.py` (self — all 20 lines)

**Existing pattern** (config.py lines 6–20):
```python
DATABASE_URL:              str   = os.environ["DATABASE_URL"]        # fail-fast if missing
API_TOKEN:                 str   = os.environ["API_TOKEN"]           # fail-fast if missing
FACE_MATCH_HIGH_THRESHOLD: float = float(os.getenv("FACE_MATCH_HIGH_THRESHOLD", "0.65"))
LOG_LEVEL:                 str   = os.getenv("LOG_LEVEL", "INFO").upper()
```

**New vars to add** (same style — optional with defaults, fail-fast only for true secrets):
```python
# ── Telegram digest (Phase 3) ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")   # empty = digest disabled
TELEGRAM_CHAT_ID:   str = os.getenv("TELEGRAM_CHAT_ID",   "")   # empty = digest disabled

# ── HDBSCAN clustering (Phase 3) ─────────────────────────────────────────────
CLUSTER_MIN_SIZE:    int = int(os.getenv("CLUSTER_MIN_SIZE",    "5"))
CLUSTER_MIN_SAMPLES: int = int(os.getenv("CLUSTER_MIN_SAMPLES", "2"))
```

---

### `services/web/src/api/clusters.ts` (modify — add 3 mutation hooks)

**Analog:** `services/web/src/api/persons.ts` (exact — same useMutation + invalidateQueries pattern)

**Imports pattern** (persons.ts lines 1–3):
```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch, getSettings } from './client';
import type { ClusterItem } from '../types/api';
```

**Existing query hook pattern** (clusters.ts lines 18–26 — keep as-is):
```typescript
export function useClusters() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['clusters'],
    queryFn:  listClusters,
    staleTime: 60_000,
    enabled:   !!apiToken,
  });
}
```

**New mutation hooks — copy exactly from persons.ts useMutation pattern** (persons.ts lines 54–84):
```typescript
export function usePromoteCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, personId }: { clusterId: string; personId: string }) =>
      authFetch(`/clusters/${clusterId}/promote?person_id=${personId}`, { method: 'POST' })
        .then(r => r.json()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
      qc.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}

export function useIgnoreCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) =>
      authFetch(`/clusters/${clusterId}/ignore`, { method: 'POST' }).then(r => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clusters'] }),
  });
}

export function useRestoreCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) =>
      authFetch(`/clusters/${clusterId}/ignore`, { method: 'DELETE' }).then(r => r.json()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clusters'] }),
  });
}
```

**Also add `listClusters` with `include_ignored` param**:
```typescript
export async function listIgnoredClusters(): Promise<ClusterItem[]> {
  return authFetch('/clusters?include_ignored=true').then(r => r.json());
}

export function useIgnoredClusters() {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey: ['clusters', 'ignored'],
    queryFn:  listIgnoredClusters,
    staleTime: 60_000,
    enabled:   !!apiToken,
  });
}
```

---

### `services/web/src/types/api.ts` (modify — extend ClusterItem)

**Analog:** `services/web/src/types/api.ts` (self — lines 97–104)

**Existing ClusterItem** (api.ts lines 97–104):
```typescript
export interface ClusterItem {
  id:                      string;
  representative_frame_id: number | null;
  appearance_count:        number;
  first_seen:              string | null;
  last_seen:               string | null;
  thumbnail_url:           string | null;  // "/frames/{id}/image"
}
```

**Add one field** (same optional-null style, placed after `thumbnail_url`):
```typescript
export interface ClusterItem {
  id:                      string;
  representative_frame_id: number | null;
  appearance_count:        number;
  first_seen:              string | null;
  last_seen:               string | null;
  thumbnail_url:           string | null;  // "/frames/{id}/image"
  ignored:                 boolean;        // Phase 3: true = marked as noise
}
```

---

### `services/web/src/pages/ClustersPage.tsx` (modify — add Ignored section)

**Analog:** `services/web/src/pages/PeoplePage.tsx` + `services/web/src/pages/ClustersPage.tsx` (self)

**Section/grid layout pattern** (ClustersPage.tsx lines 71–82):
```tsx
{/* Active cluster grid */}
{clusters.length > 0 && (
  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
    {clusters.map(cluster => (
      <ClusterCard key={cluster.id} cluster={cluster} onEnrolled={handleClusterEnrolled} />
    ))}
  </div>
)}
```

**Add collapsed Ignored section** after the active grid (same Tailwind style):
```tsx
{/* Ignored clusters — collapsed section */}
{ignoredClusters.length > 0 && (
  <div className="mt-8">
    <button
      onClick={() => setIgnoredOpen(v => !v)}
      className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 mb-3"
    >
      <span>{ignoredOpen ? '▾' : '▸'}</span>
      <span>Ignored ({ignoredClusters.length})</span>
    </button>
    {ignoredOpen && (
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {ignoredClusters.map(cluster => (
          <ClusterCard
            key={cluster.id}
            cluster={cluster}
            onEnrolled={handleClusterEnrolled}
            showRestoreOnly
          />
        ))}
      </div>
    )}
  </div>
)}
```

**New state vars** (same useState pattern as ClustersPage lines 8–10):
```tsx
const [ignoredOpen, setIgnoredOpen] = useState(false);
const { data: ignoredClusters = [] } = useIgnoredClusters();
```

**Loading/error pattern** (ClustersPage.tsx lines 39–53 — copy exactly, no changes needed):
```tsx
{isLoading && (
  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
    {Array.from({ length: 8 }).map((_, i) => (
      <div key={i} className="aspect-[4/5] bg-gray-200 rounded-xl animate-pulse" />
    ))}
  </div>
)}
{isError && (
  <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
    Failed to load clusters: {error instanceof Error ? error.message : 'Unknown error'}
  </div>
)}
```

---

### `services/web/src/components/ClusterCard.tsx` (modify — change enroll submit action)

**Analog:** `services/web/src/components/ClusterCard.tsx` (self — lines 27–46)

**Current submit action** (ClusterCard.tsx lines 27–46 — REPLACE lines 34–39 only):
```typescript
// CURRENT — remove this:
const rematchPerson = useRematchPerson();
// ...
const person = await createPerson.mutateAsync(name);
await rematchPerson.mutateAsync(person.id);   // ← replace this line
```

**New submit action** (RESEARCH.md Pattern 7):
```typescript
// REPLACE WITH:
import { useCreatePerson } from '../api/persons';
import { usePromoteCluster, useIgnoreCluster } from '../api/clusters';

// In component:
const createPerson   = useCreatePerson();
const promoteCluster = usePromoteCluster();
const ignoreCluster  = useIgnoreCluster();

async function handleEnroll(e: React.FormEvent) {
  e.preventDefault();
  const name = personName.trim();
  if (!name) return;
  setEnrollError(null);
  try {
    const person = await createPerson.mutateAsync(name);
    // Phase 3: promote cluster (targeted bulk update) instead of rematch (full library scan)
    await promoteCluster.mutateAsync({ clusterId: cluster.id, personId: person.id });
    setEnrollDone(true);
    setEnrolling(false);
    onEnrolled?.();
  } catch (err) {
    setEnrollError(err instanceof Error ? err.message : 'Enroll failed');
  }
}

const isPending = createPerson.isPending || promoteCluster.isPending;
```

**Noise button — change from disabled to active** (ClusterCard.tsx lines 93–99):
```tsx
// CURRENT (disabled):
<button disabled title="Coming soon — Phase 3" className="...cursor-not-allowed">
  🚫 Noise
</button>

// REPLACE WITH:
<button
  onClick={() => ignoreCluster.mutate(cluster.id)}
  disabled={ignoreCluster.isPending}
  className="text-xs text-gray-500 hover:text-red-600 border border-gray-200 rounded px-2 py-1.5 transition-colors"
>
  {ignoreCluster.isPending ? '…' : '🚫 Noise'}
</button>
```

**Add Restore button variant** (when `showRestoreOnly` prop is true):
```tsx
// ClusterCard Props interface — add optional prop:
interface Props {
  cluster:        ClusterItem;
  onEnrolled?:    () => void;
  showRestoreOnly?: boolean;   // Phase 3: true when rendered in Ignored section
}

// In actions area:
{props.showRestoreOnly ? (
  <button
    onClick={() => restoreCluster.mutate(cluster.id)}
    disabled={restoreCluster.isPending}
    className="flex-1 text-xs font-medium text-gray-600 hover:text-blue-600 border border-gray-200 rounded px-2 py-1.5 transition-colors"
  >
    {restoreCluster.isPending ? '…' : '↩ Restore'}
  </button>
) : (
  /* existing enroll + noise buttons */
)}
```

---

### `.env.example` (modify — append Telegram vars)

**Analog:** `.env.example` (self — lines 28–30 show existing Phase 3 vars already partially present)

**Existing clustering section** (.env.example lines 28–30):
```
# ── Clustering (HDBSCAN — Phase 3) ──────────────────────────────────────────
CLUSTER_MIN_SIZE=3
CLUSTER_MIN_SAMPLES=2
```

**Add Telegram section** (same comment-header style, append before `# ── API`):
```
# ── Telegram Digest (Phase 3) ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
```

> **NOTE:** `.env.example` already has `CLUSTER_MIN_SIZE` and `CLUSTER_MIN_SAMPLES` — do **not** add them again. Only add the two `TELEGRAM_*` vars.

---

### `docs/n8n-clustering-workflow.json` (new — no code analog)

**No analog in codebase.** See RESEARCH.md for n8n workflow JSON structure. The file is a documentation artifact (exported n8n workflow JSON), not executable code. Planner should reference RESEARCH.md workflow section for the JSON structure.

---

## Shared Patterns

### Bearer Token Authentication
**Source:** `services/api/app/auth.py` (all 27 lines) + `services/api/app/main.py` lines 55–63
**Apply to:** All new routers in `clustering.py` and `digest.py`

```python
# auth.py — used as Depends() at router registration, never per-endpoint:
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from . import config

_bearer = HTTPBearer(auto_error=False)

async def require_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    if credentials is None or credentials.credentials != config.API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# In main.py:
app.include_router(router, dependencies=[Depends(require_token)])
```

### asyncpg Connection Pool Pattern
**Source:** `services/api/app/persons.py` lines 61–78, 93–96, 214–224, 334–349
**Apply to:** All DB operations in `clustering.py` and `digest.py`

```python
# Acquire connection from pool — always use async with:
pool = await get_pool()
async with pool.acquire() as conn:
    row = await conn.fetchrow("SELECT ...", param1)     # single row
    rows = await conn.fetch("SELECT ...", param1)        # multiple rows
    val  = await conn.fetchval("SELECT COUNT(*) ...")    # scalar
    result = await conn.execute("UPDATE ...", param1)    # "UPDATE N" string
    await conn.executemany("UPDATE ...", list_of_tuples) # bulk DML

# Pattern: acquire once per logical operation, not once per statement
# (see persons.py rematch: separate acquire blocks for each phase)
```

### 404 Guard Pattern
**Source:** `services/api/app/persons.py` lines 143–149, 287–291, 397–401
**Apply to:** All `/{id}` endpoints in `clustering.py`

```python
row = await conn.fetchrow("SELECT id FROM unknown_clusters WHERE id = $1", cluster_id)
if not row:
    raise HTTPException(status_code=404, detail="Cluster not found")
```

### Response Model Construction Pattern
**Source:** `services/api/app/persons.py` lines 79–85, 109–118
**Apply to:** All Pydantic response construction in `clustering.py` and `digest.py`

```python
# Always construct Pydantic model explicitly from row dict:
return PersonResponse(
    id=row["id"],
    name=row["name"],
    notes=row["notes"],
    created_at=row["created_at"],
    enrollment_count=0,
)
# NOT: PersonResponse(**dict(row))  — asyncpg Record is not a plain dict
```

### TanStack Query v5 Mutation Hook Pattern
**Source:** `services/web/src/api/persons.ts` lines 54–84
**Apply to:** All new hooks in `services/web/src/api/clusters.ts`

```typescript
// v5 ONLY: object-form useMutation (no positional args)
export function useDeletePerson() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deletePerson,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['persons'] }),
  });
}
// Invalidate BOTH ['clusters'] and ['persons'] when promote succeeds
// Invalidate only ['clusters'] for ignore/restore
```

### authFetch Pattern
**Source:** `services/web/src/api/client.ts` lines 16–37
**Apply to:** All new raw API functions in `clusters.ts`

```typescript
// POST with no body:
authFetch(`/clusters/${id}/ignore`, { method: 'POST' }).then(r => r.json())

// POST with query param (not body):
authFetch(`/clusters/${id}/promote?person_id=${personId}`, { method: 'POST' }).then(r => r.json())

// DELETE:
authFetch(`/clusters/${id}/ignore`, { method: 'DELETE' }).then(r => r.json())
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `docs/n8n-clustering-workflow.json` | config/doc | — | No n8n workflow exports exist in codebase; use RESEARCH.md workflow section for JSON structure |

---

## Metadata

**Analog search scope:** `services/api/app/`, `services/web/src/api/`, `services/web/src/components/`, `services/web/src/pages/`, `services/web/src/types/`, `db/migrations/`, `.env.example`
**Files scanned:** 17
**Pattern extraction date:** 2025-07
