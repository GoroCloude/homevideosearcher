# Research Summary  HomeVideoSearcher v2.0

**Synthesized:** 2026-05-22
**Sources read:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS-v2.md, PROJECT.md
**Overall Confidence:** HIGH  all research grounded in direct codebase audit of the live v1.1 system plus verified package versions from PyPI/Docker Hub.

---

## Stack Additions

> Only **new** dependencies introduced by v2.0 features. The v1.1 stack (FastAPI, asyncpg, InsightFace, YOLO, pgvector, React/Vite/TanStack Query) is unchanged.

| Package | Version | Service | Reason |
|---------|---------|---------|--------|
| `watchdog` | `>=4.0` | `watcher` (new) | Filesystem event daemon. v4.0+ exposes `on_closed()` which fires only after a file write is fully flushed  critical for avoiding partial-file uploads. |
| `requests` | `>=2.32` | `watcher` (new) | HTTP call from watcher to `POST ingestion-worker:8001/ingest`. No async needed; daemon is single-threaded. |
| `minio` | `==7.2.20` | `watcher` (new) | Already in `ingestion-worker`  reuse same SDK version. Watcher needs it to upload files from local folder to MinIO. |

**New Docker Compose service:** `services/watcher/`  Python 3.11-slim-bookworm container; ~50 MB image footprint; only `watchdog + minio + requests`. Do NOT embed in `ingestion-worker` (would share ML model memory and risk OOM).

**No schema migrations needed.** The `unknown_clusters.label` column already exists in `001_schema.sql`. No new tables or columns are required for any of the three v2.0 features.

---

## Feature Table Stakes

### 1. Cluster Nickname Labeling

A feature is "done" when ALL of the following are true:

- [ ] `PATCH /clusters/{id}/label` endpoint exists and writes to the **existing** `unknown_clusters.label` column (not a new column)
- [ ] `GET /clusters` SELECT includes `uc.label`; `ClusterResponse` exposes `label: Optional[str]`
- [ ] ClusterCard shows label below the cluster dates; clicking a pencil icon reveals an inline text input
- [ ] Saving (Enter / blur) calls the PATCH; a toast confirms; React Query cache is invalidated
- [ ] Empty string / null accepted — clears the label
- [ ] Telegram digest caption uses label when present: `"{label or 'Unknown person'}  seen {count}"`
- [ ] Label max 100 chars enforced at the API layer (no migration needed  validation only)

**Not done:** label  enrollment; label never creates a `known_persons` row; clusters are never merged on label collision.

---

### 2. Person Appearance Page

A feature is "done" when ALL of the following are true:

- [ ] Route `/people/:id` registered in `App.tsx`; `PersonCard.tsx` links to it
- [ ] `GET /persons/{id}/appearances` endpoint returns one row **per video** (not per face detection): `{video_id, video_minio_key, first_ts_ms, appearance_count, thumbnail_url}`
- [ ] `thumbnail_url` is a **presigned URL generated server-side** in the aggregation query  not fetched individually by the browser (avoids N+1 connection pool exhaustion)
- [ ] `PersonDetailPage.tsx` renders: page header (name, total count, date range), video list sorted newest-first with face thumbnail + appearance count + timestamp deep-link
- [ ] Timestamp links navigate to `/videos/:id?t={ts_ms}`  VideoDetailPage already handles `?t` seek
- [ ] 404 returned (and shown in UI) when `person_id` does not exist
- [ ] Empty state shown when person exists but has zero matched detections

**Not done:** Calendar heat-map and date-range filter are optional differentiators, not required for done.

---

### 3. Watch-Folder Auto-Ingest

A feature is "done" when ALL of the following are true:

- [ ] New `watcher` service in `docker-compose.yml` on `home-infra` network; configurable via `WATCH_HOST_PATH`, `WATCH_STABLE_SECONDS`, `WATCH_USE_POLLING` env vars
- [ ] Only `.mp4 / .mov / .avi / .mkv` files trigger pipeline; all other extensions ignored
- [ ] File stability confirmed before upload: `on_closed()` event (watchdog  4.0) **or** size-poll fallback (2 consecutive equal readings, minimum 1s gap)
- [ ] `on_moved` events handled (rsync/atomic-rename pattern) in addition to `on_created`
- [ ] MinIO key uses timestamp prefix to avoid collisions: `videos/{YYYYMMDD_HHMMSS}_{filename}`
- [ ] **Startup scan**: on container start, walk `/watch` and call `POST ingestion-worker:8001/ingest` for every eligible file (ingest endpoint returns `skipped` for already-done files  cost is one DB query per file)
- [ ] `WATCH_USE_POLLING=true` mode available for NFS/CIFS mounts where inotify is absent
- [ ] Structured log lines: `DETECTED | STABLE | UPLOADING | QUEUED | SKIPPED | ERROR`
- [ ] Manual upload button in web UI is NOT removed  watch-folder is additive

**Not done:** No dedicated watch-folder UI page needed; ingested files appear in the existing Videos list automatically.

---

## Architecture Integration

### How Each Feature Plugs In

```
api service (existing)
 clustering.py    ADD  PATCH /clusters/{id}/label
                       ADD  label field to ClusterResponse + GET /clusters SELECT
 persons.py       ADD  GET /persons/{id}/appearances  (new grouped aggregation query)
 digest.py        MODIFY  caption logic: use uc.label when NOT NULL

web service (existing React SPA)
 types/api.ts     ADD  label: string | null  to ClusterItem
 api/clusters.ts   ADD  patchClusterLabel() + useLabelCluster() mutation hook
 ClusterCard.tsx   ADD  label display + pencil-icon inline edit
─ App.tsx          ADD  <Route path="people/:id" element={<PersonDetailPage />} />
 PersonCard.tsx   ADD  <Link to={`/people/${id}`}>
 api/persons.ts   ADD  getPersonAppearances() + usePersonAppearances() hook
 pages/           NEW  PersonDetailPage.tsx

watcher service (new)
 services/watcher/
     Dockerfile        (python:3.11-slim-bookworm + watchdog + minio + requests)
     main.py           (watchdog Observer + FileSystemEventHandler + startup scan)
     .env vars         (WATCH_HOST_PATH, MINIO_*, INGESTION_WORKER_URL, ...)

docker-compose.yml    ADD  watcher service block + volume mount
```

### Data Flow Summary

**Cluster labeling:**
`ClusterCard (type label)  PATCH /clusters/{id}/label  UPDATE unknown_clusters SET label=$1  invalidateQueries(['clusters'])  ClusterCard re-renders`
`n8n cron  POST /digest/send  SELECT uc.label  caption = f"{label or 'Unknown person'}  seen {count}"`

**Person appearance:**
`PersonCard click  /people/{id}  usePersonAppearances(id)  GET /persons/{id}/appearances  GROUP BY v.id aggregation (server-side presigned URLs)  PersonDetailPage video list`

**Watch-folder ingest:**
`file lands in /watch  watchdog on_closed/on_created  stability check  minio.put_object("videos/{ts}_{filename}")  POST ingestion-worker:8001/ingest {minio_key}  existing pipeline (unchanged)`

### Key Architectural Constraints (carry forward from v1.1)

- `ingestion-worker` and `api` share no code; watcher calls `ingestion-worker:8001` directly (no auth required  internal Docker network only)
- ML models are sequential-only: YOLO then InsightFace, never concurrent. The watcher is the first external mechanism that can break this invariant  a `asyncio.Semaphore(1)` in the ingestion worker's `process_video` is **mandatory** before watch-folder goes live
- Pool `max_size=10` on API service  server-side presigned URL generation on the appearances endpoint prevents pool exhaustion from concurrent thumbnail requests

---

## Critical Pitfalls

Prioritized by severity. Top 5 must be addressed before the corresponding feature ships.

###  1. Concurrent Ingestion  OOM Kill (CRITICAL  blocks Phase 3)

**Risk:** Watch daemon submits multiple files rapidly. `BackgroundTasks` has no concurrency limit. Two concurrent `process_video` calls = YOLO (~1.5 GB) + InsightFace (~2 GB)  2 = ~7 GB, leaving 1 GB for OS. Docker `memory: 5g` limit kills the worker mid-pipeline. Videos stuck in `status='processing'` indefinitely (reset_stale_processing handles restart, but pipeline work is lost).

**Prevention:** Add `asyncio.Semaphore(1)` in `ingestion-worker/app/pipeline.py` wrapping `process_video`. Expose as `MAX_CONCURRENT_INGEST=1` env var. This must be implemented before the watcher service is wired up.

---

###  2. Partial File Upload When Watchdog Fires Too Early (CRITICAL  blocks Phase 3)

**Risk:** `FileCreatedEvent` fires when the OS creates the inode, not when the write completes. A 1 GB file being copied fires the event seconds before copy finishes. FFmpeg receives a truncated file, ingestion fails, video stays `status='failed'`. No automatic recovery.

**Prevention:** Use `on_closed()` handler (watchdog  4.0  fires after file handle is closed). For watchdog < 4.0 or NFS mounts: poll `os.path.getsize()` every 0.5s until stable for 2 consecutive readings (minimum 1s wait). Add `on_moved` handler for rsync atomic-rename pattern.

---

###  3. PATCH Writes Wrong Column Name (CRITICAL  blocks Phase 1)

**Risk:** `unknown_clusters.label` already exists AND is already read by `videos.py:list_video_faces()` at line 317 as `uc.label AS cluster_label`. If the new PATCH writes to a *different* column (e.g., `nickname`, `label_name`), the video detail faces tab silently breaks  labels typed by the user never appear in the video detail view. No error is thrown.

**Prevention:** Before writing any code, run `\d unknown_clusters` on the production DB to confirm the column name. The PATCH must write to `unknown_clusters.label`  no migration needed, no new column.

---

###  4. Files Dropped During Watcher Downtime Are Silently Lost (HIGH  blocks Phase 3)

**Risk:** Watchdog has no persistent event history. A container restart, crash, or `docker-compose restart` means any files deposited during downtime generate no `FileCreatedEvent`. They sit in `/watch` forever, never ingested.

**Prevention:** Implement a startup scan: on container start, iterate all eligible files in `/watch` and call `POST ingestion-worker:8001/ingest` for each. The ingest endpoint returns `status: "skipped"` for already-done files (one lightweight DB query per file). This closes the gap entirely and also mitigates the MinIO-upload-succeeds/ingest-call-fails race condition.

---

###  5. N+1 DB Pool Exhaustion on Person Appearance Page (HIGH  blocks Phase 2)

**Risk:** Naively using `/frames/{frame_id}/image` for each thumbnail on the appearance page = one API request per thumbnail. 30 videos  3 thumbnails = 90 simultaneous browserAPI round-trips, each consuming an asyncpg pool slot. With `max_size=10`, 80 requests queue waiting for a pool connection; visible page freeze.

**Prevention:** Generate presigned URLs server-side inside the `GET /persons/{id}/appearances` aggregation SQL query (same pattern as `list_video_detections`). Return `thumbnail_url` as a pre-generated presigned URL in the JSON response. This reduces page load to 1 pool connection for the aggregation query.

---

## Recommended Build Order

### Phase 1  Cluster Nickname Labeling
**Scope:** `clustering.py` (PATCH endpoint + ClusterResponse update) + `digest.py` (caption logic) + `ClusterCard.tsx` (label display + inline edit)
**Rationale:** Smallest blast radius. No new infrastructure. DB column already exists  zero migration risk. If something breaks, it only affects the cluster label display; no other feature is impacted. Fastest path to user-visible value.
**Must avoid:** L-1 (write to correct column), L-2 (add label to GET response), L-6 (debounce the PATCH, not onChange)
**Delivers:** Users can label clusters; labeled names appear in Telegram digest

---

### Phase 2  Person Appearance Page
**Scope:** `persons.py` (new grouped appearances endpoint) + `PersonDetailPage.tsx` + route + PersonCard link
**Rationale:** Purely additive  new endpoint, new page, zero modifications to existing endpoints. Builds on the well-established `GET /persons/{id}/faces` pattern already in `persons.py`. Can be built and tested without touching Phase 1 work.
**Must avoid:** A-1 (server-side presigned URLs to prevent N+1), A-2 (GROUP BY in SQL, not Python), A-3 (sort by `COALESCE(v.recorded_at, v.ingested_at)`), A-5 (set React Query staleTime < 3600s)
**Delivers:** Clicking a person card navigates to all their footage with timestamps

---

### Phase 3  Watch-Folder Auto-Ingest
**Scope:** `services/watcher/` (new service: Dockerfile + main.py) + `docker-compose.yml` additions
**Rationale:** Most infrastructure work, but completely isolated  no existing service is modified. The integration surface is a single HTTP call to an existing endpoint (`POST ingestion-worker:8001/ingest`). Built last to avoid blocking Phases 1 and 2 on Docker Compose changes.
**Must resolve before starting:** W-4/XC-4 semaphore in ingestion worker (implement in Phase 3 sprint, before watcher goes live)
**Must avoid:** W-1 (stability check), W-2 (NFS polling mode), W-3 (startup scan), W-5 (timestamp-prefix MinIO keys), W-7 (on_moved handler)
**Delivers:** Files dropped in a watched folder are automatically ingested  zero manual steps

---

## Key Decisions Needed

These are open questions that require an explicit choice before implementation begins on the relevant phase.

| # | Decision | Affects | Options | Recommendation |
|---|----------|---------|---------|----------------|
| D-1 | **Watchdog file stability strategy** | Phase 3 | (a) Use `on_closed()`  requires watchdog  4.0; (b) size-poll fallback | Use `on_closed()` as primary; add size-poll as fallback. Pin `watchdog>=4.0` in watcher requirements. |
| D-2 | **MinIO key scheme for watcher uploads** | Phase 3 | (a) `videos/{YYYYMMDD_HHMMSS}_{filename}`; (b) `videos/{uuid4()}_{filename}`; (c) basename only (current manual-upload behavior  unsafe) | Option (a): timestamp prefix is human-readable and collision-resistant. Never reuse option (c). |
| D-3 | **NFS/CIFS watch folder support** | Phase 3 | (a) Always use polling observer; (b) Default inotify, add `WATCH_USE_POLLING=true` env var | Option (b): inotify is more efficient for local ext4 volumes; expose polling as explicit opt-in. |
| D-4 | **Semaphore scope for ingestion worker** | Phase 3 prerequisite | (a) `Semaphore(1)`  serialize all jobs; (b) `Semaphore(2)` | Option (a): 8 GB RAM / CPU-only leaves no headroom for two concurrent ML pipelines. |
| D-5 | **Person appearance page thumbnail strategy** | Phase 2 | (a) Server-side presigned URLs in aggregation response; (b) individual `/frames/{id}/image` per thumbnail | Option (a) is mandatory (see Pitfall #5). Choose representative frame as `MIN(ts_ms)` per video unless a better heuristic is available. |
| D-6 | **Labeled cluster UUID drift** | Phase 1 ongoing | (a) Accept as known limitation + log warning; (b) Add label-inheritance logic on re-cluster | Option (a) for v2.0. Document explicitly. The single-user case makes this edge case rare. |

---

## Sources

- `services/api/app/clustering.py`  live codebase (PATCH target, ClusterResponse, run_clustering logic)
- `services/api/app/persons.py`  live codebase (existing /faces endpoint pattern; appearances endpoint design)
- `services/api/app/digest.py`  live codebase (caption logic to modify)
- `services/api/app/videos.py`  live codebase (list_video_faces confirms label column at line 317)
- `db/init/001_schema.sql`  confirms `unknown_clusters.label TEXT` column pre-exists
- `docker-compose.yml`  confirms `home-infra` external network, service names, port assignments
- STACK.md (watchdog, minio, requests version verification)
- FEATURES.md (table-stakes, anti-features, dependency analysis per feature)
- ARCHITECTURE.md (component map, data flow, build order rationale, Docker networking)
- PITFALLS-v2.md (severity-ranked pitfall catalog with prevention strategies)
