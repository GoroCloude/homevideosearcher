# Architecture Research  v2.0

**Researched:** 2026-05-22  
**Confidence:** HIGH  based on full source code audit of services/api, services/web, services/ingestion-worker, docker-compose.yml, and db/init/001_schema.sql  
**Scope:** Integration analysis for three new v2.0 features: cluster nickname labeling, person appearance page, watch-folder auto-ingest

---

## Component Map

### System Architecture (v1.1 baseline  v2.0 delta)

```

                     External Infra (not in docker-compose.yml)           
   MinIO (:9000)   n8n (cron)   Cloudflare Tunnel                         
─-
        S3 API           POST /cluster/run, POST /digest/send
                        
               
                 api service  (FastAPI :8000/8003)                       
                 Existing routers: /persons /search /videos /frames      
                                   /clusters /digest                     
                 v2.0 MODIFIED: clustering.py  +PATCH /clusters/{id}/label 
                 v2.0 MODIFIED: persons.py  +GET /persons/{id}/appearances 
                 v2.0 MODIFIED: digest.py  include label in caption     
               ─
                                       asyncpg
                                      
               ─
                 postgres (pgvector :5432)                               
                 Tables: videos, frames, detections, face_detections,    
                         known_persons, person_embeddings, unknown_clusters
                 v2.0 NO schema changes needed (label col exists already) 
               ─
       
          ┐
            ingestion-worker  (FastAPI :8001)                             
            POST /ingest  accepts {minio_key}                            
            POST /ingest/batch                                            
            v2.0 UNCHANGED                                                
          ─
                                                    BACKGROUND TASK
                                                   
          
            ML pipeline (inside ingestion-worker)                         
            FFmpeg  YOLOv8n  InsightFace buffalo_l  pgvector match     
          
       
          ─
            watcher service  (NEW v2.0)                                  
            Python daemon using watchdog library                         
            Watches /watch volume mount                                  
          │  On file arrival:                                             
              1. Upload to MinIO via minio-py (same endpoint/creds)      
              2. POST http://ingestion-worker:8001/ingest {minio_key}    
          ─
       
          
            web service  (nginx :80 serving React SPA)                   
            v2.0 MODIFIED: App.tsx  +/people/:id route                  
            v2.0 MODIFIED: ClusterCard.tsx  label display + edit form   
            v2.0 NEW:      PersonDetailPage.tsx                          
            v2.0 MODIFIED: types/api.ts  ClusterItem.label field        
            v2.0 MODIFIED: api/clusters.ts  patchClusterLabel()         
            v2.0 NEW:      api hook usePersonAppearances()               
          
```

---

### New Components

| Component | Type | Location | Purpose |
|-----------|------|----------|---------|
| `watcher` service | New Docker Compose service | `services/watcher/` | Daemon that monitors `/watch` volume, uploads files to MinIO, triggers ingestion |
| `PersonDetailPage.tsx` | New React page component | `services/web/src/pages/` | Displays all video appearances for a known person with timestamps/thumbnails |
| `PATCH /clusters/{id}/label` | New FastAPI endpoint | `services/api/app/clustering.py` | Store freeform label text on an unknown cluster |
| `GET /persons/{id}/appearances` | New FastAPI endpoint | `services/api/app/persons.py` | Return per-video appearance aggregates for a known person |
| `usePersonAppearances()` | New TanStack Query hook | `services/web/src/api/persons.ts` | Client-side hook for appearance endpoint |
| Migration `004_*` | New SQL migration | `db/migrations/` | Not required (label col exists), but add as explicit no-op or skip |

### Modified Components

| Component | File | What Changes |
|-----------|------|-------------|
| `clustering.py` | `services/api/app/clustering.py` | Add `PATCH /clusters/{id}/label` endpoint; add `label` field to `ClusterResponse` Pydantic model; add `label` to `GET /clusters` SELECT |
| `digest.py` | `services/api/app/digest.py` | Add `uc.label` to SELECT query; update caption logic to use label when present (`{label or "Unknown person"}  seen {count}, {first}  {last}`) |
| `ClusterCard.tsx` | `services/web/src/components/ClusterCard.tsx` | Add label display (below dates); add inline edit form (pencil icon  text input  save); call `patchClusterLabel` mutation |
| `ClusterItem` type | `services/web/src/types/api.ts` | Add `label: string \| null` field |
| `clusters.ts` API | `services/web/src/api/clusters.ts` | Add `patchClusterLabel(id, label)` function; add `useLabelCluster()` mutation hook |
| `persons.py` | `services/api/app/persons.py` | Add `GET /persons/{id}/appearances` endpoint + Pydantic models |
| `persons.ts` API | `services/web/src/api/persons.ts` | Add `getPersonAppearances(id)` function; add `usePersonAppearances(id)` query hook |
| `PersonCard.tsx` | `services/web/src/components/PersonCard.tsx` | Add clickable link to `/people/{id}` |
| `App.tsx` | `services/web/src/App.tsx` | Add `<Route path="people/:id" element={<PersonDetailPage />} />` |
| `docker-compose.yml` | root | Add `watcher` service block with volume mount, env vars, network |

---

## Data Flow Changes

### Feature 1: Cluster Nickname Labeling

```
User types label in ClusterCard
   PATCH /api/clusters/{id}/label  {"label": "Delivery person"}
     UPDATE unknown_clusters SET label=$1 WHERE id=$2
       TanStack invalidateQueries(['clusters'])
         ClusterCard re-renders with label displayed

n8n cron  POST /api/digest/send
   SELECT uc.id, uc.label, uc.appearance_count, ...
     caption = f"{label or 'Unknown person'}  seen {count}, {first}  {last}"
       Telegram sendMediaGroup
```

**Key detail:** `unknown_clusters.label` column was defined in `001_schema.sql` (the initial schema). It is **not** added by any existing migration (002, 003 cover other columns). The live database created from init schema has this column already. No migration required.

### Feature 2: Person Appearance Page

```
User clicks person name/card (PeoplePage)
   Navigate to /people/{id}
     PersonDetailPage mounts
       usePersonAppearances(id)  GET /api/persons/{id}/appearances
         SQL:
            SELECT
              v.id AS video_id,
              v.minio_key AS video_minio_key,
              MIN(f.ts_ms) AS ts_ms,
              COUNT(fd.id) AS appearance_count,
              MIN(f.id) AS representative_frame_id
            FROM face_detections fd
            JOIN frames f ON f.id = fd.frame_id
            JOIN videos v ON v.id = f.video_id
            WHERE fd.matched_person_id = $1
            GROUP BY v.id, v.minio_key
            ORDER BY v.ingested_at DESC
         Returns list of {video_id, video_minio_key, ts_ms, appearance_count, thumbnail_url}
           thumbnail_url = "/frames/{representative_frame_id}/image"
            (reuses existing GET /frames/{id}/image  presigned MinIO redirect)
```

**Key detail:** No new DB tables or columns. All needed data already exists across `face_detections  frames  videos`. The `/frames/{id}/image` redirect endpoint already exists and is public (self-secured by presigned URL). The appearance page reuses it without change.

**thumbnail_url strategy:** Use `MIN(f.id)` (or `MIN(f.ts_ms)`) as representative frame per video. This is the first frame in the video where the person appears  simple, cheap, no MinIO calls during query.

### Feature 3: Watch-folder Auto-ingest

```
New file lands in /watch (host bind mount)
   watchdog FileCreatedEvent in watcher service
     wait for file stable (no size change for N seconds, e.g. 2s)
       minio_key = "videos/{filename}"
       minio_client.put_object(bucket="videos", key=minio_key, data=file_bytes)
         POST http://ingestion-worker:8001/ingest {"minio_key": minio_key}
           ingestion-worker returns {"status": "queued", "video_id": "..."}
             watcher logs success
               (optional) move or delete source file from /watch
```

**Key detail on stability wait:** Watchdog fires `on_created` as soon as the OS creates the inode. For large video files being copied, the file is not fully written yet. The watcher **must** poll for file size stability before uploading  otherwise it sends a partial file to MinIO. Recommended: poll `os.path.getsize()` every 0.5s, proceed when size unchanged for 2+ consecutive checks with a minimum wait of 1s.

**Key detail on ingestion-worker auth:** The `ingestion-worker/app/main.py` has **no `require_token` middleware**. `POST /ingest` is unauthenticated  intentionally, since it's an internal service only. The watcher does not need to send an `Authorization` header to ingestion-worker. (Only the `api` service on :8003 has bearer-token auth.)

---

## Build Order Recommendation

**Recommended: Feature 1  Feature 2  Feature 3**

### Phase 1: Cluster Nickname Labeling (smallest scope, zero risk)
- **Rationale:** Pure additive change. DB column already exists. No new infrastructure. Only touches one API endpoint + one frontend component + digest caption. If something goes wrong, it has zero impact on other features.
- **Backend:** Add `PATCH /clusters/{id}/label` to `clustering.py`; add `label` to `ClusterResponse` and `GET /clusters` SELECT.
- **Frontend:** Add `label` to `ClusterItem` type; add `patchClusterLabel` to `clusters.ts`; add label display + edit to `ClusterCard.tsx`.
- **Digest:** Update `digest.py` caption to use label.
- **No migration needed.**

### Phase 2: Person Appearance Page (medium scope, additive)
- **Rationale:** New read-only endpoint + new React page. Does not modify any existing endpoint. Reuses existing `/frames/{id}/image` thumbnail pattern. Builds on the established `GET /persons/{id}/faces` pattern in `persons.py`.
- **Backend:** Add `GET /persons/{id}/appearances` to `persons.py` with `PersonAppearanceItem` + `PersonAppearancesResponse` Pydantic models.
- **Frontend:** Add `PersonDetailPage.tsx`; add route to `App.tsx`; add `usePersonAppearances` hook; make `PersonCard` clickable.
- **No migration needed.**

### Phase 3: Watch-folder Auto-ingest (most infra work, isolated)
- **Rationale:** New standalone service. Does not touch `api` or `web` at all. Only integration point is `http://ingestion-worker:8001/ingest` (unchanged). Can be built and tested independently. Most infra risk (Docker Compose changes, volume mounts, env vars) is isolated here.
- **New service:** `services/watcher/`  Python 3.11, `watchdog` + `minio` libraries, Dockerfile.
- **docker-compose.yml:** Add `watcher` service block.
- **No migration needed.**

**Why this order:**
- Feature 1 gives the quickest user-visible win with minimal risk  good momentum starter.
- Feature 2 is additive-only on the backend and follows the same pattern as existing `/faces` endpoint  low complexity, clear model.
- Feature 3 is the most infra-heavy but also the most isolated  no existing service is modified, so it can be built last without blocking features 1 or 2.

---

## Docker Networking Notes (watcher service)

### Network topology

All existing Docker Compose services join the **`home-infra` external network**:
```yaml
networks:
  home-infra:
    external: true
```
MinIO, n8n, and Cloudflare Tunnel also run on this same `home-infra` network (they are not in this docker-compose.yml but are pre-existing on the host).

The `watcher` service must be added to this same network to reach both MinIO and ingestion-worker:

```yaml
watcher:
  build: ./services/watcher
  environment:
    WATCH_PATH: /watch
    MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
    MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
    MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
    MINIO_BUCKET_VIDEOS: ${MINIO_BUCKET_VIDEOS:-videos}
    MINIO_USE_SSL: ${MINIO_USE_SSL:-false}
    INGESTION_WORKER_URL: http://ingestion-worker:8001
    DEST_PREFIX: ${WATCHER_DEST_PREFIX:-videos}
    STABILITY_WAIT_SEC: ${WATCHER_STABILITY_WAIT:-2}
    LOG_LEVEL: ${LOG_LEVEL:-INFO}
  volumes:
    - ${WATCH_HOST_PATH:-/mnt/nas/incoming}:/watch:ro
  depends_on:
    - ingestion-worker
  networks:
    - home-infra
```

### Hostname resolution

| Target | Hostname from watcher | Port | Notes |
|--------|----------------------|------|-------|
| MinIO | `minio` | 9000 | Resolves via `home-infra` Docker network  same as ingestion-worker and api use |
| ingestion-worker | `ingestion-worker` | 8001 | Resolves via Docker Compose service name on `home-infra` |
| postgres | Not needed |  | Watcher never touches DB directly |
| api | Not needed |  | Watcher calls ingestion-worker directly, not api |

### Why watcher calls ingestion-worker, NOT api

The `api` service `POST /ingest`... wait  there is no `/ingest` on the api service. The api service handles `/videos`, `/persons`, `/clusters`, etc. The ingestion-worker at `:8001` is the service that owns `POST /ingest`. This is the correct and direct path. The watcher should POST to `http://ingestion-worker:8001/ingest`  not through the api service.

**No bearer token needed:** `POST /ingest` on ingestion-worker has no auth middleware. It is internal-only, accessible only within the Docker network. The watcher is a trusted internal service.

### Volume mount strategy

Use a **read-only bind mount** from the host watch folder into `/watch` inside the container. The watcher should **move processed files** to a subdirectory (e.g., `/watch/.processed/`) or **delete them** after successful upload, to prevent re-processing on container restart.

Since the container has `:ro` mount, the watcher cannot move/delete. Two options:
1. Use `:rw` mount and have watcher move file to `.processed/` subfolder after upload
2. Use `:ro` mount and maintain an in-memory/file set of already-uploaded keys (lost on restart)

**Recommendation:** Use `:rw` mount and move to `{watch_path}/.processed/{filename}` after successful ingest confirmation. This survives container restarts and prevents double-ingestion without needing a separate state store.

### File deduplication

The ingestion-worker already handles idempotency: if `minio_key` already exists with `status=done`, it returns `{"status": "skipped"}`. So even if watcher re-uploads on restart, ingestion-worker will not reprocess.

---

## DB Schema Changes Needed

**No schema changes required for any of the three v2.0 features.**

| Feature | DB Change | Reason |
|---------|-----------|--------|
| Cluster nickname labeling |  None | `unknown_clusters.label TEXT` column already exists in `001_schema.sql` (initial schema, not a migration). The live database has this column from day 1. |
| Person appearance page | ❌ None | All data exists: `face_detections  frames  videos` join provides video_id, ts_ms, appearance count. No new columns needed. |
| Watch-folder auto-ingest |  None | Watcher writes to MinIO and calls ingestion-worker HTTP API. No direct DB access. |

### Migration file recommendation

Even though no schema change is needed, add a `004_v2.0_marker.sql` migration as a no-op comment block:

```sql
-- v2.0 migration marker  no schema changes required.
-- unknown_clusters.label was present in 001_schema.sql from initial deploy.
-- This file exists to keep migration numbering continuous.
```

This keeps the migration sequence clean for future reference.

---

## Detailed Integration Points by Feature

### Feature 1: Cluster Nickname Labeling  Touch Map

| Layer | File | Change type | Detail |
|-------|------|-------------|--------|
| API endpoint | `services/api/app/clustering.py` | ADD endpoint | `PATCH /clusters/{cluster_id}/label`  body `{"label": str}`, UPDATE unknown_clusters SET label=$1 WHERE id=$2 |
| API model | `services/api/app/clustering.py` | MODIFY | Add `label: Optional[str]` to `ClusterResponse`; add `uc.label` to `GET /clusters` SELECT |
| Digest caption | `services/api/app/digest.py` | MODIFY | Add `uc.label` to SELECT; caption = `f"{uc['label'] or 'Unknown person'}  seen..."` |
| TS type | `services/web/src/types/api.ts` | MODIFY | Add `label: string \| null` to `ClusterItem` interface |
| API client | `services/web/src/api/clusters.ts` | ADD function + hook | `patchClusterLabel(id, label)` + `useLabelCluster()` mutation |
| UI component | `services/web/src/components/ClusterCard.tsx` | MODIFY | Display label below dates; add pencil/edit inline UI; call `useLabelCluster` |

### Feature 2: Person Appearance Page  Touch Map

| Layer | File | Change type | Detail |
|-------|------|-------------|--------|
| API endpoint | `services/api/app/persons.py` | ADD endpoint + models | `GET /persons/{person_id}/appearances` with `PersonAppearanceItem`, `PersonAppearancesResponse` |
| TS type | `services/web/src/types/api.ts` | ADD | `PersonAppearanceItem`, `PersonAppearancesResponse` interfaces |
| API client | `services/web/src/api/persons.ts` | ADD function + hook | `getPersonAppearances(id)` + `usePersonAppearances(id)` |
| New page | `services/web/src/pages/PersonDetailPage.tsx` | CREATE | Grid of video appearance cards with thumbnail, ts_ms, appearance_count; link to video detail |
| Router | `services/web/src/App.tsx` | MODIFY | Add `<Route path="people/:id" element={<PersonDetailPage />} />` |
| PersonCard | `services/web/src/components/PersonCard.tsx` | MODIFY | Wrap card/name in `<Link to={/people/${person.id}}>` |

**PersonAppearanceItem shape (recommended):**
```typescript
interface PersonAppearanceItem {
  video_id:         string;
  video_minio_key:  string;        // for display/navigation
  ts_ms:            number;        // first appearance timestamp in video
  appearance_count: number;        // total face detections in this video
  thumbnail_url:    string;        // "/frames/{representative_frame_id}/image"
}
```

**SQL query for appearances endpoint:**
```sql
SELECT
    v.id::text              AS video_id,
    v.minio_key             AS video_minio_key,
    MIN(f.ts_ms)            AS ts_ms,
    COUNT(fd.id)::int       AS appearance_count,
    MIN(f.id)               AS representative_frame_id
FROM face_detections fd
JOIN frames f ON f.id = fd.frame_id
JOIN videos v ON v.id = f.video_id
WHERE fd.matched_person_id = $1
GROUP BY v.id, v.minio_key
ORDER BY MIN(COALESCE(v.recorded_at, v.ingested_at)) DESC
```

### Feature 3: Watch-folder Auto-ingest  Touch Map

| Layer | File | Change type | Detail |
|-------|------|-------------|--------|
| New service | `services/watcher/` | CREATE directory | Python package with Dockerfile |
| Watcher entrypoint | `services/watcher/watcher.py` | CREATE | watchdog Observer loop |
| Watcher config | `services/watcher/config.py` | CREATE | Env var loading (WATCH_PATH, MINIO_*, INGESTION_WORKER_URL, etc.) |
| Dockerfile | `services/watcher/Dockerfile` | CREATE | FROM python:3.11-slim; pip install minio watchdog requests |
| requirements.txt | `services/watcher/requirements.txt` | CREATE | minio, watchdog, requests (no ML libraries needed) |
| docker-compose.yml | root | MODIFY | Add `watcher:` service block with volume, env, network |
| .env.example | root | MODIFY | Add WATCH_HOST_PATH, WATCHER_DEST_PREFIX, WATCHER_STABILITY_WAIT |

**Watcher service is intentionally minimal:** no FastAPI, no asyncpg, no ML. Just `minio` + `watchdog` + `requests`. Dockerfile will be tiny (~200MB vs ~8GB for ingestion-worker).

---

## Risk Assessment

| Risk | Severity | Feature | Mitigation |
|------|----------|---------|------------|
| `label` column absent from live DB | LOW | Feature 1 | Column defined in init schema (001_schema.sql); live DB was created from this schema; confirmed present |
| Watchdog `on_created` fires before file fully written | MEDIUM | Feature 3 | Implement file stability check (poll size until stable); standard pattern for watch daemons |
| MinIO key collision (two watchers or duplicate filenames) | LOW | Feature 3 | `minio_key = "videos/{filename}"`  if same filename uploaded twice, MinIO silently overwrites; ingestion-worker returns `skipped` on second call |
| watcherMinIO connection via `minio:9000` (internal hostname) | LOW | Feature 3 | All existing services use `minio:9000` successfully; `home-infra` network provides DNS resolution |
| `PersonDetailPage` thumbnail loading performance | LOW | Feature 2 | Uses existing `/frames/{id}/image` redirect  each thumbnail is a separate HTTP request; paginate or lazy-load if appearance_count is high |
| `digest.py` label display for clusters without labels | NONE | Feature 1 | `COALESCE(uc.label, 'Unknown person')` or Python `uc["label"] or "Unknown person"`  trivial null guard |

---

*Source: Full source audit of services/api/app/\*.py, services/web/src/\*\*/\*.ts(x), docker-compose.yml, db/init/001_schema.sql, db/migrations/*.sql  2026-05-22*
