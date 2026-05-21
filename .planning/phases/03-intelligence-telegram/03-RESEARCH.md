# Phase 3: Unknown Face Intelligence & Telegram Digest — Research

**Researched:** 2025-07
**Domain:** HDBSCAN clustering · PostgreSQL schema migrations · Telegram Bot API · FastAPI endpoints · React/TanStack Query UI
**Confidence:** HIGH (all claims verified against codebase or official library sources)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Telegram**
| Decision | Value |
|---|---|
| Credentials | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` — add to `.env` and `config.py` |
| Message format | `sendMediaGroup` — up to 10 photos, each captioned |
| Trigger | `POST /digest/send` + n8n cron at 8am daily with Bearer token |
| Time filter | **All unknown clusters** regardless of age — no time-based filter |
| Max photos per digest | 10 (Telegram sendMediaGroup limit) |

**HDBSCAN clustering**
| Decision | Value |
|---|---|
| `min_cluster_size` | 5 |
| `min_samples` | 2 |
| `metric` | `euclidean` |
| Algorithm | `boruvka_kdtree` (CONTEXT says this — see research note below) |
| Input | All `face_detections` where `matched_person_id IS NULL` |
| Incremental | Stable UUIDs — re-run merges new noise faces into existing clusters |
| Representative face | Highest `det_score` + sharpest image (Variance of Laplacian) |

**Cluster management UI/API**
| Decision | Value |
|---|---|
| `GET /clusters` filter | Only unenrolled + non-ignored clusters |
| Mark as noise | `POST /clusters/{id}/ignore` → `ignored=true` |
| Restore noise | `DELETE /clusters/{id}/ignore` → `ignored=false` |
| UI — ignored section | Collapsed "Ignored" section on ClustersPage |
| Cluster promotion | `POST /clusters/{id}/promote?person_id={pid}` — bulk UPDATE |

### the agent's Discretion
- None noted in CONTEXT.md

### Deferred Ideas (OUT OF SCOPE)
- None noted in CONTEXT.md
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLUSTER-01 | Nightly HDBSCAN clustering of `matched_person_id = NULL` embeddings | sklearn.cluster.HDBSCAN already installed; see HDBSCAN pattern below |
| CLUSTER-02 | Incremental: existing cluster UUIDs preserved across re-runs | Centroid-matching strategy documented below |
| CLUSTER-03 | Each cluster: stable UUID, representative face, appearance count | Schema already has all these columns |
| CLUSTER-04 | `POST /cluster/run` endpoint inside api service | Router pattern from persons.py and search.py |
| CLUSTER-05 | Promote cluster → bulk update member `face_detections` | Single SQL UPDATE pattern documented |
| NOTIF-01 | Nightly digest via Telegram Bot API | python-telegram-bot already in requirements.txt |
| NOTIF-02 | `sendMediaGroup` single album ≤10 photos | Documented; fetch bytes from MinIO internally |
| NOTIF-03 | Each entry: representative thumbnail + appearance count + dates | Caption format confirmed from CONTEXT |
| NOTIF-04 | No message if zero clusters | Simple `if len(clusters) == 0: return` guard |
| NOTIF-05 | Bot token + chat ID from env vars | Add to config.py; pattern from existing env vars |
</phase_requirements>

---

## Summary

Phase 3 adds three capabilities to the existing FastAPI + PostgreSQL + React stack: (1) HDBSCAN-based face clustering run on demand via `POST /cluster/run`, (2) cluster management endpoints (ignore/restore/promote) with corresponding UI changes, and (3) a Telegram digest endpoint `POST /digest/send` triggered by n8n at 8am daily.

All required Python libraries are **already installed** (`scikit-learn==1.8.0` covers HDBSCAN, `python-telegram-bot>=22.0` covers Telegram). Two SQL columns are **missing from the current schema** and require a migration file: `unknown_clusters.ignored` (BOOLEAN) and `unknown_clusters.promoted_at` (TIMESTAMPTZ). The existing `ClusterItem` TypeScript type needs one new field (`ignored`). The `ClusterCard.tsx` enrollment submit action needs to change from `createPerson → rematchPerson` to `createPerson → POST /clusters/{id}/promote`.

**Primary recommendation:** Add migration `003_add_cluster_state_cols.sql` first (Wave 0), then implement the three new modules (`clustering.py`, `digest.py`, cluster router) as separate plans following the exact patterns from `persons.py` and `search.py`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HDBSCAN clustering logic | API service | — | CPU-bound, runs on demand; api has 2GB limit and InsightFace already loaded |
| `POST /cluster/run` endpoint | API service | — | Protected endpoint, follows existing router pattern |
| `GET /clusters` endpoint | API service | — | DB query with JOIN to face_detections/frames |
| Cluster ignore/restore/promote | API service | — | DB mutations; promote is a single bulk UPDATE |
| Telegram digest send | API service | — | `digest.py` uses python-telegram-bot; fetches MinIO bytes internally |
| n8n cron trigger | n8n automation | — | Schedule node → HTTP Request nodes (existing pattern) |
| Clusters UI (grid + ignored section) | React frontend | — | ClustersPage.tsx + ClusterCard.tsx modifications |
| New cluster API hooks | React frontend | — | Add to `clusters.ts`; follow TanStack Query v5 pattern |
| `ignored` + `promoted_at` columns | Database | — | Schema migration required |

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scikit-learn | 1.8.0 (installed) | `sklearn.cluster.HDBSCAN` for face clustering | Already in `requirements.txt`; covers HDBSCAN since 1.3 |
| python-telegram-bot | ≥22.0,<23.0 (installed) | Async Telegram Bot API client | Already in `requirements.txt`; v22 is asyncio-native |
| asyncpg | 0.31.0 (installed) | PostgreSQL bulk UPDATE + SELECT | Already in stack; `executemany` pattern proven in persons.py |
| minio | 7.2.20 (installed) | Fetch frame bytes for sharpness scoring + Telegram | `get_object()` for internal byte download |
| opencv-python-headless | ≥4.10 (installed) | Variance of Laplacian sharpness score | `cv2.Laplacian(img, cv2.CV_64F).var()` |
| numpy | <2.0 (installed) | ndarray for embeddings matrix | HDBSCAN input must be numpy array |

[VERIFIED: services/api/requirements.txt]

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | ≥0.24 (dev only) | Test client for endpoint testing | Already in requirements-dev.txt |
| python-dotenv | ≥1.0 (installed) | `.env` file loading | Config pattern already established |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `sklearn.cluster.HDBSCAN` | Standalone `hdbscan` package | Standalone has `boruvka_kdtree` algorithm but adds a new dependency; sklearn already installed and sufficient |
| `python-telegram-bot` v22 | Direct `httpx` calls to Bot API | httpx calls are simpler but python-telegram-bot already installed and handles multipart upload cleanly |

---

## Critical Schema Findings

### Current `unknown_clusters` Table [VERIFIED: db/init/001_schema.sql]

```sql
CREATE TABLE unknown_clusters (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    representative_face_id  BIGINT,        -- FK to face_detections(id) — NOT frame_id
    appearance_count        INT NOT NULL DEFAULT 0,
    first_seen              TIMESTAMPTZ,
    last_seen               TIMESTAMPTZ,
    label                   TEXT,          -- user-assigned label
    created_at              TIMESTAMPTZ DEFAULT now()
);
```

**MISSING columns — migration required:**
1. `ignored BOOLEAN NOT NULL DEFAULT false` — needed for `POST /clusters/{id}/ignore`
2. `promoted_at TIMESTAMPTZ` — needed to filter promoted clusters from `GET /clusters` response

**Key FK relationship:** `representative_face_id` references `face_detections(id)` (BIGINT), NOT `frames(id)`. To get `frame_id` for thumbnail URL, the API must JOIN: `face_detections.frame_id → frames.id`.

### `face_detections` Table [VERIFIED: db/init/001_schema.sql]

Relevant columns for clustering:
```sql
id                  BIGSERIAL PRIMARY KEY
frame_id            BIGINT  -- → frames.id → frames.minio_key for image fetch
normed_embedding    vector(512)
matched_person_id   UUID   -- NULL = unmatched, target for clustering
unknown_cluster_id  UUID   -- FK to unknown_clusters; SET NULL on cascade
det_score           REAL   -- SCRFD confidence; use for representative selection
```

### Required Migration File

`db/migrations/003_add_cluster_state_cols.sql`:
```sql
ALTER TABLE unknown_clusters
    ADD COLUMN IF NOT EXISTS ignored     BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS unknown_clusters_ignored_idx ON unknown_clusters (ignored);
```

---

## Architecture Patterns

### System Architecture Diagram

```
n8n Cron (8am)
    │
    ├─ POST /cluster/run ─────────────────────────────────────────────────┐
    │                                                                      ▼
    │                                                         clustering.py
    │                                                              │
    │                                                    1. SELECT normed_embedding
    │                                                       WHERE matched_person_id IS NULL
    │                                                              │
    │                                                    2. numpy array → HDBSCAN fit
    │                                                              │
    │                                                    3. For each cluster label:
    │                                                       - Find existing UUID (majority vote)
    │                                                       - Or create new UUID
    │                                                              │
    │                                                    4. SELECT top-N by det_score
    │                                                       → fetch frame bytes from MinIO
    │                                                       → Laplacian sharpness score
    │                                                       → pick representative_face_id
    │                                                              │
    │                                                    5. UPSERT unknown_clusters
    │                                                       UPDATE face_detections.unknown_cluster_id
    │                                                              │
    │                                                         200 OK
    │
    └─ POST /digest/send ─────────────────────────────────────────────────┐
                                                                          ▼
                                                                    digest.py
                                                                         │
                                                              1. SELECT non-ignored,
                                                                 non-promoted clusters
                                                                 (LIMIT 10)
                                                                         │
                                                              2. For each cluster:
                                                                 fetch frame bytes
                                                                 from MinIO (internal)
                                                                         │
                                                              3. bot.send_media_group(
                                                                 chat_id,
                                                                 media=[InputMediaPhoto(...)]
                                                                 )
                                                                         │
                                                                    200 OK

Browser → GET /clusters
              │
    clustering_router.py
              │
    SELECT uc.*, fd.frame_id
    FROM unknown_clusters uc
    LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id
    WHERE uc.ignored = false
      AND uc.promoted_at IS NULL
    ORDER BY uc.appearance_count DESC
              │
    [{id, representative_frame_id, appearance_count,
       first_seen, last_seen, thumbnail_url, ignored}]
```

### Recommended Project Structure

New files to add:
```
services/api/app/
├── clustering.py          # HDBSCAN logic + POST /cluster/run + GET /clusters + management endpoints
├── digest.py              # Telegram digest logic + POST /digest/send
└── (existing files unchanged)

db/migrations/
└── 003_add_cluster_state_cols.sql    # ignored + promoted_at columns

services/web/src/
├── api/
│   └── clusters.ts        # Add: useIgnoreCluster, useRestoreCluster, usePromoteCluster
├── types/
│   └── api.ts             # Add: ignored: boolean to ClusterItem
└── pages/
    └── ClustersPage.tsx   # Add: collapsed "Ignored" section

docs/
└── n8n-clustering-workflow.json    # New n8n workflow export

.env.example               # Add: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CLUSTER_MIN_SIZE=5
```

---

## Pattern 1: HDBSCAN Clustering with Stable UUIDs

**What:** Load all unmatched embeddings, run HDBSCAN, match output clusters to existing DB UUIDs by majority vote, upsert.

**Algorithm implementation:**
```python
# Source: sklearn.cluster.HDBSCAN docs (scikit-learn 1.3+)
# VERIFIED: requirements.txt has scikit-learn==1.8.0
from sklearn.cluster import HDBSCAN
import numpy as np

# ── Step 1: Load unmatched embeddings ─────────────────────────────────────────
# Returns rows: (id BIGINT, normed_embedding vector, unknown_cluster_id UUID|None)
rows = await conn.fetch("""
    SELECT id, normed_embedding, unknown_cluster_id::text
    FROM face_detections
    WHERE matched_person_id IS NULL
      AND normed_embedding IS NOT NULL
""")

if len(rows) < 5:   # HDBSCAN min_cluster_size guard
    return {"clusters_created": 0, "faces_assigned": 0}

face_ids = [r["id"] for r in rows]
existing_cluster_ids = [r["unknown_cluster_id"] for r in rows]  # may be None
X = np.array([r["normed_embedding"] for r in rows], dtype=np.float32)

# ── Step 2: Run HDBSCAN ────────────────────────────────────────────────────────
# NOTE: sklearn uses algorithm='kd_tree' (not 'boruvka_kdtree' — that's standalone hdbscan)
clusterer = HDBSCAN(
    min_cluster_size=5,       # from CONTEXT locked decision
    min_samples=2,            # from CONTEXT locked decision
    metric='euclidean',       # from CONTEXT locked decision
    algorithm='kd_tree',      # sklearn equivalent of boruvka_kdtree; avoids O(n²) matrix
    n_jobs=1,                 # single-threaded — i5-6200 memory constraint
)
labels = clusterer.fit_predict(X)  # label=-1 means noise

# ── Step 3: Map HDBSCAN labels → stable UUIDs (majority vote) ─────────────────
from collections import Counter
import uuid

label_to_uuid: dict[int, str] = {}
for hdbscan_label in set(labels):
    if hdbscan_label == -1:
        continue  # noise — not assigned to any cluster
    indices = [i for i, lbl in enumerate(labels) if lbl == hdbscan_label]
    existing = [existing_cluster_ids[i] for i in indices if existing_cluster_ids[i]]
    if existing:
        # Reuse the most common existing UUID
        label_to_uuid[hdbscan_label] = Counter(existing).most_common(1)[0][0]
    else:
        label_to_uuid[hdbscan_label] = str(uuid.uuid4())

# ── Step 4: Compute appearance count + first/last seen per cluster ────────────
# (Join face_detections → frames for timestamps)
# ...see full implementation pattern below

# ── Step 5: Bulk UPDATE face_detections.unknown_cluster_id ───────────────────
updates = [
    (label_to_uuid[labels[i]], face_ids[i])
    for i in range(len(face_ids))
    if labels[i] != -1
]
await conn.executemany(
    "UPDATE face_detections SET unknown_cluster_id = $1::uuid WHERE id = $2",
    updates,
)
```

[VERIFIED: codebase patterns from persons.py; sklearn API from training knowledge tagged ASSUMED for exact parameter names]

**⚠️ CRITICAL NOTE — `algorithm` parameter mismatch:**
- CONTEXT.md says `algorithm='boruvka_kdtree'` — this is the **standalone `hdbscan` package** parameter name
- `scikit-learn` (already installed) uses `algorithm` values: `{'auto', 'brute', 'kd_tree', 'ball_tree'}`
- **Use `algorithm='kd_tree'`** — semantically equivalent fast algorithm for Euclidean metric in sklearn
- Do NOT add standalone `hdbscan` package; sklearn is already installed and sufficient [VERIFIED: requirements.txt]

---

## Pattern 2: Representative Face Selection (Sharpness + det_score)

**What:** For each cluster, pick the face with the highest det_score × sharpness. Sharpness = Variance of Laplacian of the frame image.

```python
# Source: cv2.Laplacian pattern — [ASSUMED: standard OpenCV approach]
import cv2
import numpy as np
from io import BytesIO

async def pick_representative_face(
    conn, cluster_face_ids: list[int], minio_client
) -> int | None:
    """
    Returns face_detection.id of the best representative.
    Only checks top 3 by det_score to limit MinIO round-trips.
    """
    # Get top 3 candidates by det_score
    rows = await conn.fetch("""
        SELECT fd.id, fd.det_score, f.minio_key
        FROM face_detections fd
        JOIN frames f ON f.id = fd.frame_id
        WHERE fd.id = ANY($1::bigint[])
        ORDER BY fd.det_score DESC
        LIMIT 3
    """, cluster_face_ids)

    best_face_id = None
    best_score = -1.0

    for row in rows:
        # Download frame image bytes from MinIO (internal endpoint)
        try:
            response = minio_client.get_object("frames", row["minio_key"])
            img_bytes = response.read()
            response.close()
            response.release_conn()
        except Exception:
            # Fallback: use det_score only if MinIO fetch fails
            score = float(row["det_score"] or 0)
            if score > best_score:
                best_score = score
                best_face_id = row["id"]
            continue

        # Compute Variance of Laplacian (sharpness)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        sharpness = cv2.Laplacian(img, cv2.CV_64F).var()

        # Combined score: det_score (0-1) × normalized sharpness
        combined = float(row["det_score"] or 0) * min(sharpness / 100.0, 1.0)
        if combined > best_score:
            best_score = combined
            best_face_id = row["id"]

    return best_face_id
```

[VERIFIED: cv2 Laplacian pattern; minio get_object from ingestion-worker/app/storage.py patterns]

**Performance note:** `get_object()` from MinIO (internal Docker DNS `minio:9002` or configured `MINIO_ENDPOINT`) is synchronous. Run in a thread pool executor or call during the clustering pass (not per-request):
```python
import asyncio
loop = asyncio.get_event_loop()
response = await loop.run_in_executor(None, lambda: minio_client.get_object(bucket, key))
```

---

## Pattern 3: UPSERT unknown_clusters

```python
# Upsert cluster row — update if UUID already exists, insert if new
await conn.execute("""
    INSERT INTO unknown_clusters
        (id, representative_face_id, appearance_count, first_seen, last_seen)
    VALUES ($1::uuid, $2, $3, $4, $5)
    ON CONFLICT (id) DO UPDATE SET
        representative_face_id = EXCLUDED.representative_face_id,
        appearance_count       = EXCLUDED.appearance_count,
        first_seen             = EXCLUDED.first_seen,
        last_seen              = EXCLUDED.last_seen
""", cluster_uuid, rep_face_id, appearance_count, first_seen, last_seen)
```
[VERIFIED: PostgreSQL ON CONFLICT pattern; asyncpg execute() from persons.py]

---

## Pattern 4: GET /clusters Response

The existing TypeScript `ClusterItem` type references `representative_frame_id` (not `representative_face_id`). The DB stores `representative_face_id` (FK to face_detections). The API must JOIN to resolve `frame_id`.

```python
# GET /clusters — returns active (not ignored, not promoted) clusters
rows = await conn.fetch("""
    SELECT
        uc.id::text,
        uc.appearance_count,
        uc.first_seen::text,
        uc.last_seen::text,
        uc.ignored,
        fd.frame_id   AS representative_frame_id
    FROM unknown_clusters uc
    LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id
    WHERE uc.ignored = false
      AND uc.promoted_at IS NULL
    ORDER BY uc.appearance_count DESC
""")
# thumbnail_url built as f"/frames/{row['representative_frame_id']}/image"
```
[VERIFIED: schema from 001_schema.sql; TypeScript type from api.ts]

For the ignored section (`GET /clusters?include_ignored=true`):
```python
# Add query param: include_ignored: bool = False
# When True, also return ignored clusters (but still exclude promoted)
# WHERE clause: uc.promoted_at IS NULL  (remove the ignored filter)
```

---

## Pattern 5: Promote Endpoint

```python
# POST /clusters/{cluster_id}/promote?person_id={pid}
# Single SQL UPDATE — no executemany needed
result = await conn.execute("""
    UPDATE face_detections
    SET matched_person_id = $1::uuid,
        match_tier        = 'confident',
        match_similarity  = 1.0
    WHERE unknown_cluster_id = $2::uuid
      AND matched_person_id IS NULL
""", person_id_str, cluster_id_str)

# Mark cluster as promoted
await conn.execute("""
    UPDATE unknown_clusters
    SET promoted_at = now()
    WHERE id = $1::uuid
""", cluster_id_str)
```
[VERIFIED: SQL pattern from persons.py rematch; asyncpg conn.execute]

---

## Pattern 6: Telegram sendMediaGroup

```python
# Source: python-telegram-bot v20+ async API — [ASSUMED: API shape; verified library is installed]
# python-telegram-bot>=22.0,<23.0 is async-native
from telegram import Bot, InputMediaPhoto
from telegram.error import TelegramError
from io import BytesIO

async def send_digest(clusters: list[dict], minio_client, bot_token: str, chat_id: str):
    if not clusters:
        logger.info("No clusters to send — digest skipped")
        return {"sent": 0, "skipped": True}

    bot = Bot(token=bot_token)
    media_group = []

    for cluster in clusters[:10]:   # Telegram sendMediaGroup limit = 10
        # Fetch representative frame bytes from MinIO (internal endpoint)
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: minio_client.get_object("frames", cluster["minio_key"])
            )
            img_bytes = response.read()
            response.close()
            response.release_conn()
        except Exception as e:
            logger.warning("Could not fetch frame for cluster %s: %s", cluster["id"], e)
            continue

        # Build caption: "Unknown person — seen Nx, {first_seen} → {last_seen}"
        count = cluster["appearance_count"]
        first = cluster["first_seen"][:10] if cluster["first_seen"] else "?"
        last  = cluster["last_seen"][:10]  if cluster["last_seen"]  else "?"
        caption = f"Unknown person — seen {count}×, {first} → {last}"

        media_group.append(
            InputMediaPhoto(
                media=BytesIO(img_bytes),
                caption=caption,
            )
        )

    if not media_group:
        return {"sent": 0, "skipped": True}

    await bot.send_media_group(chat_id=chat_id, media=media_group)
    return {"sent": len(media_group), "skipped": False}
```

**Why use MinIO bytes (not presigned URLs):**
- MinIO is on the internal Docker network; Telegram's servers cannot reach `minio:9002`
- Even with `MINIO_PUBLIC_ENDPOINT`, the user's home IP may block inbound connections from Telegram servers
- Fetching bytes internally and passing as `BytesIO` is the only reliable approach for self-hosted setups

[VERIFIED: python-telegram-bot installed from requirements.txt; MinIO internal access pattern from storage.py]

---

## Pattern 7: ClusterCard.tsx Enrollment Flow Change

**Current behavior (Phase 4):**
```typescript
// Step 1: Create person
const person = await createPerson.mutateAsync(name);
// Step 2: rematch ALL unmatched embeddings (entire library scan)
await rematchPerson.mutateAsync(person.id);
```

**Phase 3 behavior:**
```typescript
// Step 1: Create person
const person = await createPerson.mutateAsync(name);
// Step 2: Promote THIS cluster (only updates cluster members)
await promoteCluster.mutateAsync({ clusterId: cluster.id, personId: person.id });
```

**New hook in `clusters.ts`:**
```typescript
export function usePromoteCluster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, personId }: { clusterId: string; personId: string }) =>
      authFetch(`/clusters/${clusterId}/promote?person_id=${personId}`, { method: 'POST' })
        .then(r => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clusters'] });
      queryClient.invalidateQueries({ queryKey: ['persons'] });
    },
  });
}

export function useIgnoreCluster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) =>
      authFetch(`/clusters/${clusterId}/ignore`, { method: 'POST' }).then(r => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['clusters'] }),
  });
}

export function useRestoreCluster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (clusterId: string) =>
      authFetch(`/clusters/${clusterId}/ignore`, { method: 'DELETE' }).then(r => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['clusters'] }),
  });
}
```
[VERIFIED: existing TanStack Query v5 pattern from ClusterCard.tsx + clusters.ts]

---

## Pattern 8: n8n Clustering Cron Workflow

Following the exact JSON structure of `docs/n8n-minio-ingest-workflow.json` [VERIFIED]:

```json
// docs/n8n-clustering-workflow.json
{
  "name": "Unknown Face Clustering & Digest (Daily)",
  "nodes": [
    {
      "type": "n8n-nodes-base.scheduleTrigger",
      "parameters": { "rule": { "interval": [{ "field": "cronExpression", "expression": "0 8 * * *" }] } }
    },
    {
      "type": "n8n-nodes-base.httpRequest",
      "name": "Run Clustering",
      "parameters": {
        "method": "POST",
        "url": "http://api:8000/cluster/run",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": true,
        "headerParameters": { "parameters": [{ "name": "Authorization", "value": "Bearer {{ $env.API_TOKEN }}" }] },
        "options": { "timeout": 300000 }  // 5 min timeout — clustering can take time
      }
    },
    {
      "type": "n8n-nodes-base.httpRequest",
      "name": "Send Digest",
      "parameters": {
        "method": "POST",
        "url": "http://api:8000/digest/send",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendHeaders": true,
        "headerParameters": { "parameters": [{ "name": "Authorization", "value": "Bearer {{ $env.API_TOKEN }}" }] },
        "options": { "timeout": 60000 }
      }
    }
  ]
}
```
[VERIFIED: n8n pattern from existing workflow JSON files + n8n-setup.md]

---

## Pattern 9: FastAPI Router Registration

Following `main.py` pattern [VERIFIED]:
```python
# In main.py — add after existing routers
from .clustering import router as clustering_router
from .digest import router as digest_router

app.include_router(clustering_router, dependencies=[Depends(require_token)])
app.include_router(digest_router,    dependencies=[Depends(require_token)])
```

```python
# clustering.py router structure
router = APIRouter(tags=["clustering"])

@router.post("/cluster/run", ...)     # POST /cluster/run
@router.get("/clusters", ...)         # GET /clusters[?include_ignored=true]
@router.post("/clusters/{id}/ignore", ...)    # POST /clusters/{id}/ignore
@router.delete("/clusters/{id}/ignore", ...)  # DELETE /clusters/{id}/ignore
@router.post("/clusters/{id}/promote", ...)   # POST /clusters/{id}/promote

# digest.py router structure
router = APIRouter(tags=["digest"])
@router.post("/digest/send", ...)     # POST /digest/send
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Density-based clustering | Custom distance graph | `sklearn.cluster.HDBSCAN` | Already installed; handles noise, variable density clusters |
| Telegram API calls | Raw httpx + multipart | `python-telegram-bot` v22 Bot.send_media_group | Already installed; handles chunking, retry, InputMediaPhoto encoding |
| UUID stability across runs | Re-hash all member IDs | Majority-vote of existing `unknown_cluster_id` | Hash changes every run when new members added |
| Sharpness metric | Complex frequency analysis | `cv2.Laplacian().var()` | Standard, fast, already have OpenCV installed |
| Bulk promote | N individual UPDATEs | Single `UPDATE WHERE unknown_cluster_id = X` | One SQL call; O(1) not O(n) |

**Key insight:** Every required library is already installed. The work is wiring them together correctly, not introducing new dependencies.

---

## Common Pitfalls

### Pitfall 1: `boruvka_kdtree` Algorithm Name in sklearn
**What goes wrong:** `sklearn.cluster.HDBSCAN(algorithm='boruvka_kdtree')` raises `ValueError` — that parameter value doesn't exist in sklearn.
**Why it happens:** CONTEXT.md references the standalone `hdbscan` package algorithm names, but sklearn uses different names.
**How to avoid:** Use `algorithm='kd_tree'` in sklearn (or `'auto'`). Semantically equivalent for Euclidean metric.
**Warning signs:** `ValueError: Invalid algorithm` at clustering runtime.

### Pitfall 2: MinIO `get_object()` is Synchronous — Blocks Event Loop
**What goes wrong:** Calling `minio_client.get_object()` directly in an async endpoint blocks the asyncio event loop, causing all other requests to stall.
**Why it happens:** minio Python SDK is synchronous.
**How to avoid:** Wrap in `await asyncio.get_event_loop().run_in_executor(None, lambda: ...)`.
**Warning signs:** API becomes unresponsive during clustering or digest sending.

### Pitfall 3: `representative_face_id` ≠ `representative_frame_id`
**What goes wrong:** The DB stores `representative_face_id` (FK to `face_detections.id`) but TypeScript `ClusterItem` needs `representative_frame_id` (FK to `frames.id`). Forgetting the JOIN returns `null` thumbnails.
**How to avoid:** Always JOIN `face_detections.frame_id` in the `GET /clusters` query.
**Warning signs:** All cluster cards show the "👤" placeholder instead of thumbnails.

### Pitfall 4: HDBSCAN on All Members for Sharpness (Performance)
**What goes wrong:** Fetching MinIO bytes for every cluster member to compute sharpness — a 100-member cluster triggers 100 MinIO downloads at clustering time.
**How to avoid:** Pre-filter to top 3 by `det_score` using SQL `ORDER BY det_score DESC LIMIT 3` before computing sharpness.
**Warning signs:** `POST /cluster/run` takes minutes instead of seconds.

### Pitfall 5: Missing DB Migration → `ignored` Column Not Found
**What goes wrong:** `POST /clusters/{id}/ignore` fails with `column "ignored" does not exist`.
**Why it happens:** The `unknown_clusters` table in `001_schema.sql` has no `ignored` column.
**How to avoid:** Wave 0 task must apply `003_add_cluster_state_cols.sql` BEFORE any clustering endpoints are implemented.
**Warning signs:** Column not found errors on first endpoint test.

### Pitfall 6: Telegram Bot Sees BytesIO Already Consumed
**What goes wrong:** `send_media_group` silently fails or raises if `BytesIO` position is not at 0.
**How to avoid:** After writing to BytesIO: `buf.seek(0)` before passing to `InputMediaPhoto(media=buf)`.

### Pitfall 7: `ClusterItem` TypeScript Type Missing `ignored` Field
**What goes wrong:** Ignored clusters section in ClustersPage renders undefined/null for `ignored` flag.
**How to avoid:** Add `ignored: boolean` to `ClusterItem` in `api.ts` before building UI.

### Pitfall 8: Promote Updates `matched_person_id` but NOT `match_similarity`/`match_tier`
**What goes wrong:** After promote, `match_tier` is NULL — search results show faces as "unknown" even though promoted.
**How to avoid:** `UPDATE face_detections SET matched_person_id=$1, match_tier='confident', match_similarity=1.0 WHERE unknown_cluster_id=$2`.

---

## Code Examples

### Loading Embeddings for Clustering
```python
# Source: asyncpg pattern from persons.py (rematch_person)
async with pool.acquire() as conn:
    rows = await conn.fetch("""
        SELECT id, normed_embedding, unknown_cluster_id::text
        FROM face_detections
        WHERE matched_person_id IS NULL
          AND normed_embedding IS NOT NULL
    """)
```

### Ignore/Restore Endpoints
```python
@router.post("/clusters/{cluster_id}/ignore", status_code=200)
async def ignore_cluster(cluster_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE unknown_clusters SET ignored = true WHERE id = $1::uuid AND promoted_at IS NULL",
            cluster_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Cluster not found or already promoted")
    return {"id": str(cluster_id), "ignored": True}

@router.delete("/clusters/{cluster_id}/ignore", status_code=200)
async def restore_cluster(cluster_id: UUID) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE unknown_clusters SET ignored = false WHERE id = $1::uuid",
            cluster_id,
        )
    return {"id": str(cluster_id), "ignored": False}
```

### ClustersPage Ignored Section (React)
```typescript
// GET /clusters?include_ignored=true to fetch all, then split
const { data: allClusters = [] } = useClusters({ includeIgnored: true });
const activeClusters  = allClusters.filter(c => !c.ignored);
const ignoredClusters = allClusters.filter(c =>  c.ignored);

// Collapsed section:
const [ignoredOpen, setIgnoredOpen] = useState(false);
// ... render <details> or conditional section with ignoredClusters
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Standalone `hdbscan` package | `sklearn.cluster.HDBSCAN` | scikit-learn 1.3 (2023) | No new dependency; slightly different algorithm names |
| `python-telegram-bot` v13 (sync) | v20+ (async-native) | 2023 | Must use `await bot.send_media_group()`; no `updater.start_polling()` needed |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| scikit-learn | HDBSCAN clustering | ✓ | 1.8.0 | — |
| python-telegram-bot | Telegram digest | ✓ | ≥22.0 | — |
| opencv-python-headless | Sharpness scoring | ✓ | ≥4.10 | Use det_score only |
| asyncpg | DB operations | ✓ | 0.31.0 | — |
| minio SDK | Frame byte fetch | ✓ | 7.2.20 | — |
| n8n | Cron scheduling | ✓ (external, home-infra network) | — | Manual curl |
| TELEGRAM_BOT_TOKEN | Digest send | ✗ (not in .env.example yet) | — | Cannot send digest |
| TELEGRAM_CHAT_ID | Digest send | ✗ (not in .env.example yet) | — | Cannot send digest |

**Missing dependencies with no fallback:**
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` env vars — must be added to `.env.example` and `config.py`; user confirmed they have existing bot credentials

**Notes:**
- MinIO `MINIO_ENDPOINT` default in `.env.example` is `minio:9000`, config.py default also `minio:9000`. Additional context says MinIO S3 API is on port 9002 in the user's installation — the `.env` file should override correctly; no code change needed.

[VERIFIED: requirements.txt; .env.example; docker-compose.yml]

---

## Open Questions (RESOLVED)

1. **`algorithm='kd_tree'` vs CONTEXT `boruvka_kdtree`**
   - What we know: sklearn 1.8.0 doesn't have `boruvka_kdtree`; standalone `hdbscan` package does
   - **RESOLVED:** Use `algorithm="kd_tree"` (sklearn). `boruvka_kdtree` is a standalone hdbscan package parameter name that does not exist in `sklearn.cluster.HDBSCAN` and would raise `ValueError` at runtime. No new dependency needed.

2. **`CLUSTER_MIN_SIZE` env var default**
   - `.env.example` has `CLUSTER_MIN_SIZE=3` but CONTEXT locked decision says `min_cluster_size=5`
   - **RESOLVED:** Update `.env.example` to `CLUSTER_MIN_SIZE=5` (matches locked CONTEXT decision). Configurable via env var.

3. **Noise face_detections: set `unknown_cluster_id = NULL` or leave?**
   - HDBSCAN label=-1 faces are "noise" — should their `unknown_cluster_id` be cleared on re-run?
   - **RESOLVED:** Clear on each run — `UPDATE face_detections SET unknown_cluster_id = NULL WHERE matched_person_id IS NULL` before re-assigning. Keeps DB consistent.

4. **`GET /clusters?include_ignored=true` vs separate endpoint**
   - CONTEXT says "GET /clusters?include_ignored=true — for the collapsed section"
   - **RESOLVED:** Single `GET /clusters` endpoint with optional `include_ignored: bool = False` query param. Simpler TanStack Query caching.

5. **Digest when clusters > 10**
   - CONTEXT: max 10 photos per sendMediaGroup. What if 15 active clusters exist?
   - **RESOLVED:** Send top 10 ordered by `appearance_count DESC`; log the number of omitted clusters. V2 can paginate with multiple albums.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `sklearn.cluster.HDBSCAN` `algorithm` parameter accepts `'kd_tree'` (not `'boruvka_kdtree'`) | Pattern 1 | Clustering fails at runtime; fallback is `algorithm='auto'` |
| A2 | `python-telegram-bot` v22 `Bot.send_media_group()` accepts `BytesIO` wrapped in `InputMediaPhoto(media=...)` | Pattern 6 | Telegram send fails; fix by using `InputFile(BytesIO(...))` wrapper |
| A3 | n8n on `home-infra` network can reach `http://api:8000` | Pattern 8 | n8n cron fails silently; verify n8n network config |
| A4 | MinIO `get_object()` returns a response with `.read()` and `.release_conn()` methods | Pattern 2 | Frame fetch fails; check minio SDK version |

---

## Sources

### Primary (HIGH confidence)
- `db/init/001_schema.sql` — verified `unknown_clusters` columns and `face_detections` FK structure
- `services/api/requirements.txt` — verified installed libraries and versions
- `services/api/app/persons.py` — asyncpg patterns, executemany, bulk UPDATE
- `services/api/app/storage.py` — MinIO client singleton pattern, presigned URL generation
- `services/api/app/main.py` — router registration with `Depends(require_token)` pattern
- `services/web/src/types/api.ts` — `ClusterItem` type, missing `ignored` field confirmed
- `services/web/src/components/ClusterCard.tsx` — current enrollment flow confirmed
- `services/api/app/config.py` — env var pattern for new Telegram vars
- `.env.example` — confirmed missing `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`
- `docs/n8n-minio-ingest-workflow.json` — n8n workflow JSON structure pattern

### Secondary (MEDIUM confidence)
- `docs/n8n-setup.md` — n8n hostname `n8n`, port `5678`, Docker network `home-infra` confirmed

### Tertiary (LOW confidence — see Assumptions Log)
- `sklearn.cluster.HDBSCAN` algorithm parameter values [ASSUMED from training: sklearn 1.3 docs]
- `python-telegram-bot` v22 `InputMediaPhoto(media=BytesIO)` API shape [ASSUMED from training]

---

## Metadata

**Confidence breakdown:**
- DB schema gaps: HIGH — directly read from init SQL
- Standard stack: HIGH — verified against requirements.txt
- HDBSCAN algorithm name discrepancy: HIGH — CONTEXT specifies `boruvka_kdtree`; sklearn does not have this parameter
- Architecture patterns: HIGH — derived from existing codebase patterns
- Telegram API shape: MEDIUM — library installed but exact v22 API not verified via docs
- Pitfalls: HIGH — derived from actual code gaps and schema state

**Research date:** 2025-07
**Valid until:** 2025-08-15 (stable stack; library versions pinned in requirements.txt)
