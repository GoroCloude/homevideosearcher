# Phase 8: Cluster Nickname Labeling — Pattern Map

**Mapped:** 2026-05-22  
**Files analyzed:** 5 (3 backend, 2 frontend — `api.ts` is a type extension, not standalone)  
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/api/app/clustering.py` | controller | CRUD (PATCH + GET update) | `services/api/app/clustering.py` itself (ignore/restore endpoints) | **exact** |
| `services/api/app/digest.py` | service | request-response (caption logic) | `services/api/app/digest.py` itself (caption line 113) | **exact** |
| `services/web/src/types/api.ts` | type definition | — | `services/web/src/types/api.ts` (`ClusterItem` interface, lines 97–105) | **exact** |
| `services/web/src/api/clusters.ts` | API hook | request-response (mutation) | `services/web/src/api/clusters.ts` (`useIgnoreCluster`, lines 78–87) | **exact** |
| `services/web/src/components/ClusterCard.tsx` | component | event-driven (onBlur) | `services/web/src/components/ClusterCard.tsx` (inline enroll form, lines 136–155) + `PersonCard.tsx` (`addToast` usage, line 21) | **exact** |

---

## Pattern Assignments

### `services/api/app/clustering.py` — ADD `PATCH /clusters/{id}/label` + update `ClusterResponse` + update `GET /clusters` SELECT

**Analog:** `services/api/app/clustering.py` — existing `ignore_cluster` / `restore_cluster` endpoints (lines 330–359)

#### Request body model pattern
The `ignore` endpoints take no body — the new PATCH needs one. Use the `CreatePersonRequest` pattern from `persons.py` (lines 30–32):
```python
# persons.py lines 30-32 — Pydantic body model for a simple write
class CreatePersonRequest(BaseModel):
    name: str
    notes: Optional[str] = None
```
Apply the same shape for label:
```python
class ClusterLabelRequest(BaseModel):
    label: Optional[str] = None   # None / empty string → clear label
```

#### PATCH endpoint signature pattern  
Copy directly from `ignore_cluster` (lines 330–341), replacing `ignore` logic with an UPDATE to `label`:
```python
# clustering.py lines 330-341 — exact signature + pool + 404-guard pattern
@router.post("/clusters/{cluster_id}/ignore", status_code=status.HTTP_200_OK)
async def ignore_cluster(cluster_id: UUID) -> dict:
    """Set ignored=true. Cluster disappears from default GET /clusters."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET ignored = true WHERE id = $1",
            cluster_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "ignored": True}
```
The new endpoint becomes:
```python
@router.patch("/clusters/{cluster_id}/label", status_code=status.HTTP_200_OK)
async def set_cluster_label(cluster_id: UUID, body: ClusterLabelRequest) -> dict:
    label = body.label.strip() if body.label else None
    if label and len(label) > 100:
        raise HTTPException(status_code=422, detail="label must be ≤ 100 characters")
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET label = $1 WHERE id = $2",
            label, cluster_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found")
    return {"id": str(cluster_id), "label": label}
```

#### `ClusterResponse` field addition pattern  
Copy from the existing model (lines 40–48) and add `label`:
```python
# clustering.py lines 40-48 — existing ClusterResponse (ADD label field here)
class ClusterResponse(BaseModel):
    id:                      str
    representative_frame_id: Optional[int]
    appearance_count:        int
    first_seen:              Optional[str]
    last_seen:               Optional[str]
    thumbnail_url:           Optional[str]
    ignored:                 bool
    # ADD:
    label:                   Optional[str] = None
```

#### `GET /clusters` SELECT update pattern  
Current SELECT (lines 294–307) does NOT include `uc.label`. Add it:
```python
# clustering.py lines 294-307 — existing SELECT (must add uc.label column)
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
      AND uc.ignored = $1
    ORDER BY uc.appearance_count DESC
""", include_ignored)
```
Add `uc.label` to the SELECT list and pass it through in the `ClusterResponse(...)` constructor (lines 309–322).

#### Auth registration pattern  
The clustering router is already registered with `dependencies=[Depends(require_token)]` in `main.py` (line 67). The new PATCH is automatically protected — no extra wiring needed.

---

### `services/api/app/digest.py` — MODIFY caption to use `cluster.label`

**Analog:** `services/api/app/digest.py` — caption line 113 (exact target line)

#### Current caption line (line 113):
```python
# digest.py line 113 — CURRENT caption (replace this)
caption = f"Unknown person \u2014 seen {count}\u00d7, {first} \u2192 {last}"
```

#### Query update — add `uc.label` to the SELECT (lines 63–78):
```python
# digest.py lines 63-78 — existing SELECT (add uc.label here)
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
```
Add `uc.label` to the SELECT list.

#### New caption pattern (replace line 113):
```python
# digest.py line 113 — NEW caption using label with fallback
name    = cluster["label"] or "Unknown person"
caption = f"{name} \u2014 seen {count}\u00d7, {first} \u2192 {last}"
```
**Column name constraint:** Must use `uc.label` — same column already read by `videos.py:list_video_faces()` as `uc.label AS cluster_label` (line 317 of videos.py).

---

### `services/web/src/types/api.ts` — ADD `label: string | null` to `ClusterItem`

**Analog:** `services/web/src/types/api.ts` — `ClusterItem` interface (lines 97–105)

#### Current interface (lines 97–105):
```typescript
// types/api.ts lines 97-105 — ADD label field here
export interface ClusterItem {
  id:                      string;
  representative_frame_id: number | null;
  appearance_count:        number;
  first_seen:              string | null;
  last_seen:               string | null;
  thumbnail_url:           string | null;  // "/frames/{id}/image"
  ignored:                 boolean;
}
```
Add one line:
```typescript
  label:                   string | null;
```
**Pattern note:** All nullable optional API fields use `T | null` (not `T | undefined`) throughout this file — maintain that convention.

---

### `services/web/src/api/clusters.ts` — ADD `patchClusterLabel()` + `useLabelCluster()` mutation hook

**Analog:** `services/web/src/api/clusters.ts` — `ignoreCluster()` + `useIgnoreCluster()` (lines 35–37, 78–87)

#### Raw API function pattern (copy from `ignoreCluster`, line 35–37):
```typescript
// clusters.ts lines 35-37 — raw function pattern (POST with no body)
export async function ignoreCluster(clusterId: string): Promise<void> {
  await authFetch(`/clusters/${clusterId}/ignore`, { method: 'POST' });
}
```
New function sends a JSON body via PATCH:
```typescript
// NEW — follows authFetch pattern; client.ts auto-injects Content-Type: application/json
export async function patchClusterLabel(clusterId: string, label: string | null): Promise<void> {
  await authFetch(`/clusters/${clusterId}/label`, {
    method: 'PATCH',
    body: JSON.stringify({ label }),
  });
}
```

#### Mutation hook pattern (copy from `useIgnoreCluster`, lines 78–87):
```typescript
// clusters.ts lines 78-87 — useMutation hook with cache invalidation
export function useIgnoreCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) => ignoreCluster(clusterId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
      qc.invalidateQueries({ queryKey: ['clusters', 'ignored'] });
    },
  });
}
```
New hook — only invalidates `['clusters']` (label change does not affect ignored list):
```typescript
export function useLabelCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, label }: { clusterId: string; label: string | null }) =>
      patchClusterLabel(clusterId, label),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
    },
  });
}
```
**TanStack Query v5 constraint (from STATE.md):** Object-form only — no positional args. All existing hooks use `{ mutationFn, onSuccess }` — maintain that shape.

---

### `services/web/src/components/ClusterCard.tsx` — ADD label display + inline edit

**Analog:** `services/web/src/components/ClusterCard.tsx` — inline enroll form (lines 1–163), plus `PersonCard.tsx` for `addToast` usage pattern

#### Import additions (copy from ClusterCard line 1–6, add hook imports):
```typescript
// ClusterCard.tsx lines 1-6 — existing imports (add useLabelCluster + addToast)
import { useState } from 'react';
import { format, parseISO } from 'date-fns';
import type { ClusterItem } from '../types/api';
import { useCreatePerson } from '../api/persons';
import { usePromoteCluster, useIgnoreCluster, useRestoreCluster } from '../api/clusters';
import FrameThumbnail from './FrameThumbnail';
```
Add:
```typescript
import { useLabelCluster } from '../api/clusters';
import { addToast } from '../hooks/useToast';
```

#### Local state pattern (copy from ClusterCard lines 22–25):
```typescript
// ClusterCard.tsx lines 22-25 — local state for inline form (same pattern for label edit)
const [enrolling,   setEnrolling]   = useState(false);
const [personName,  setPersonName]  = useState('');
const [enrollError, setEnrollError] = useState<string | null>(null);
const [enrollDone,  setEnrollDone]  = useState(false);
```
New state for label edit:
```typescript
const [editingLabel, setEditingLabel] = useState(false);
const [labelDraft,   setLabelDraft]   = useState(cluster.label ?? '');
```

#### `addToast` usage pattern (copy from `PersonCard.tsx` line 21):
```typescript
// PersonCard.tsx line 21 — addToast from singleton (not React context)
addToast(`${person.name} deleted`, 'success');
```
Apply the same pattern on label save success:
```typescript
addToast('Label saved', 'success');
```

#### `onBlur` save handler pattern — triggers PATCH, not `onChange`:
```typescript
// NOTE: no analog exists for onBlur PATCH — construct from mutateAsync pattern in ClusterCard lines 39-51
async function handleLabelBlur() {
  const trimmed = labelDraft.trim();
  const newLabel = trimmed || null;     // empty string → null (clears label)
  if (newLabel === cluster.label) {     // no-op if unchanged
    setEditingLabel(false);
    return;
  }
  try {
    await labelCluster.mutateAsync({ clusterId: cluster.id, label: newLabel });
    addToast('Label saved', 'success');
  } catch {
    addToast('Failed to save label', 'error');
  }
  setEditingLabel(false);
}
```

#### Inline input UI pattern (copy from ClusterCard lines 136–155 — inline enroll form):
```tsx
{/* ClusterCard.tsx lines 136-155 — inline form pattern (adapt for label) */}
{enrolling && !enrollDone && (
  <form onSubmit={handleEnroll} className="flex gap-2 mt-1">
    <input
      type="text"
      value={personName}
      onChange={e => { setPersonName(e.target.value); setEnrollError(null); }}
      placeholder="Name…"
      required
      autoFocus
      className="flex-1 text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
    />
    <button
      type="submit"
      disabled={isPending || !personName.trim()}
      className="text-xs font-medium bg-blue-600 text-white rounded px-2 py-1 disabled:opacity-50"
    >
      {isPending ? '…' : 'OK'}
    </button>
  </form>
)}
```
Label edit does NOT use `<form onSubmit>` — uses `onBlur` + `onKeyDown` Enter instead:
```tsx
{editingLabel ? (
  <input
    type="text"
    value={labelDraft}
    onChange={e => setLabelDraft(e.target.value)}
    onBlur={handleLabelBlur}
    onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur(); }}
    maxLength={100}
    autoFocus
    placeholder="Add nickname…"
    className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500 w-full"
  />
) : (
  <div
    className="flex items-center gap-1 cursor-pointer group"
    onClick={() => { setLabelDraft(cluster.label ?? ''); setEditingLabel(true); }}
  >
    <span className="text-xs text-gray-700 truncate">
      {cluster.label || <span className="text-gray-400 italic">Add nickname…</span>}
    </span>
    <span className="text-gray-400 group-hover:text-gray-600 text-xs">✏</span>
  </div>
)}
```

#### Label display placement — insert in the Body section after the date lines:
```tsx
{/* ClusterCard.tsx lines 95-99 — existing body section (insert label row after this) */}
<div className="p-3 flex flex-col gap-2 flex-1">
  <div className="text-xs text-gray-500 space-y-0.5">
    <p>First seen: <span className="text-gray-700">{fmtDate(cluster.first_seen)}</span></p>
    <p>Last seen:  <span className="text-gray-700">{fmtDate(cluster.last_seen)}</span></p>
  </div>
  {/* INSERT label inline-edit row here, above the Actions section */}
```

---

## Shared Patterns

### Auth — Bearer token (all protected endpoints)
**Source:** `services/api/app/auth.py` + `services/api/app/main.py` line 67  
**Apply to:** `PATCH /clusters/{id}/label` (automatically covered — clustering router is already registered with `dependencies=[Depends(require_token)]`)

No per-endpoint auth decorator needed. The new PATCH route registered on `clustering.router` inherits protection automatically.

### `authFetch` — Frontend HTTP calls
**Source:** `services/web/src/api/client.ts` lines 16–37  
**Apply to:** `patchClusterLabel()` in `clusters.ts`

```typescript
// client.ts lines 16-37 — authFetch auto-injects Content-Type + Bearer
export async function authFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const { apiBaseUrl, apiToken } = getSettings();
  const prefix = apiBaseUrl || '/api';
  const isFormData = options.body instanceof FormData;
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
`patchClusterLabel()` just passes `{ method: 'PATCH', body: JSON.stringify({label}) }` — `Content-Type: application/json` is injected automatically by `authFetch`.

### Toast notifications
**Source:** `services/web/src/hooks/useToast.ts` lines 20–28  
**Apply to:** `ClusterCard.tsx` label save handler

```typescript
// useToast.ts line 20 — module-level singleton, callable outside React components
export function addToast(message: string, type: ToastType = 'info', durationMs = 4000): void
```
Usage in `PersonCard.tsx` line 21 (exact pattern to copy):
```typescript
addToast(`${person.name} deleted`, 'success');
addToast('Some operation failed', 'error');
```

### asyncpg pool acquire + UPDATE + 404 guard
**Source:** `services/api/app/clustering.py` lines 333–341  
**Apply to:** `PATCH /clusters/{id}/label` endpoint body

```python
# clustering.py lines 333-341 — pool acquire + execute + UPDATE 0 guard
pool = await get_pool()
async with pool.acquire() as conn:
    result = await conn.execute(
        "UPDATE unknown_clusters SET ignored = true WHERE id = $1",
        cluster_id,
    )
if result == "UPDATE 0":
    raise HTTPException(status_code=404, detail="Cluster not found")
return {"id": str(cluster_id), "ignored": True}
```

### TanStack Query v5 mutation with cache invalidation
**Source:** `services/web/src/api/clusters.ts` lines 66–76 (`usePromoteCluster`)  
**Apply to:** `useLabelCluster()` mutation hook

```typescript
// clusters.ts lines 66-76 — v5 object-form mutation (no positional args)
export function usePromoteCluster() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, personId }: { clusterId: string; personId: string }) =>
      promoteCluster(clusterId, personId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clusters'] });
      qc.invalidateQueries({ queryKey: ['clusters', 'ignored'] });
      qc.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | All 5 files have exact or near-exact analogs in the codebase. |

**Special case — inline `onBlur` PATCH:** No existing component uses `onBlur` to trigger a mutation. The closest analog is the inline enroll form in `ClusterCard.tsx` (lines 136–155) which uses `onSubmit`. The `onBlur` pattern is constructed from first principles: `e.currentTarget.blur()` on Enter keydown, guard for unchanged value, `mutateAsync` call in blur handler.

---

## Metadata

**Analog search scope:** `services/api/app/*.py`, `services/web/src/api/*.ts`, `services/web/src/components/*.tsx`, `services/web/src/types/api.ts`, `services/web/src/hooks/useToast.ts`  
**Files scanned:** 14  
**Pattern extraction date:** 2026-05-22
