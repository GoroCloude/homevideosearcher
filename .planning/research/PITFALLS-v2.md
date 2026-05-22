# Pitfalls Research — v2.0

**System:** HomeVideoSearcher — existing production system on i5-6200 / 8 GB RAM / CPU-only  
**Researched:** 2026-05-22  
**Confidence:** HIGH — all pitfalls derived directly from reading the live codebase  
**Scope:** Integration pitfalls specific to adding these three features to *this* system, not generic Python/React issues.

---

## Cluster Nickname Labeling

| # | Pitfall | Severity | Prevention |
|---|---------|----------|------------|
| L-1 | **`label` column already exists AND is already read in production** — `videos.py:list_video_faces()` line 317 already reads `uc.label AS cluster_label` and uses it for display name resolution. The PATCH endpoint MUST update the existing `label` column, not add a new column (e.g., `label_name`). Adding a second column silently breaks the `list_video_faces` display without any error. | **CRITICAL** | Verify the PATCH writes to `unknown_clusters.label`. No migration needed for the column itself — it already exists in `001_schema.sql`. Run `\d unknown_clusters` on the production DB to confirm before writing any migration. |
| L-2 | **`ClusterResponse` model does not expose `label`** — The existing `GET /clusters` response model (`ClusterResponse` in `clustering.py`) has no `label` field. Adding a PATCH endpoint without also adding `label` to the GET response means the React UI can't read back the saved label — the user types a label, saves it, refreshes, and it's gone (it's in the DB but never returned). | **HIGH** | Add `label: Optional[str] = None` to `ClusterResponse` and include `uc.label` in the `GET /clusters` SELECT query. Single-step change alongside the PATCH endpoint. |
| L-3 | **Label silently lost on UUID drift during re-clustering** — The clustering UPSERT (`clustering.py` lines 234-243) does NOT include `label` in the `ON CONFLICT DO UPDATE SET` clause — labels are correctly preserved when the same UUID is re-upserted. But if a cluster's HDBSCAN membership changes enough that the majority-vote UUID shifts (e.g., the cluster splits 50/50 across two runs), the old cluster row (with the label) orphans and a new UUID gets no label. This is silent — no error, no log. | **MEDIUM** | Accept as a known limitation of the probabilistic UUID-stability strategy. Document it. For the single-user case, add a log warning when a labeled cluster's appearance_count drops to zero after a run, so the user knows to re-label. |
| L-4 | **No length constraint on `label TEXT` column** — The schema column is unbounded `TEXT`. A user could accidentally paste a paragraph, or a UI bug could submit an empty string (`""`). No server-side guard exists. | **LOW** | Add a length check in the PATCH endpoint: reject labels longer than 100 chars or consisting only of whitespace. No migration needed — this is API-layer validation only. |
| L-5 | **Race condition: PATCH during `POST /cluster/run`** — Step 6 of `run_clustering()` does a bulk `UPDATE face_detections SET unknown_cluster_id = NULL` before re-assigning cluster UUIDs. If a PATCH to update `label` runs concurrently with this, the label update succeeds on the old cluster row while the row is being re-assigned a new UUID. Result: the labeled cluster's `appearance_count` is stale (old value) and its `face_detections` now point elsewhere. | **LOW** | Single-user system — simultaneous API calls are unlikely. If it becomes a concern, wrap the cluster/run upsert steps in a transaction and add a row-level lock. For now, document as known. |
| L-6 | **React UI: direct onChange PATCH floods API** — If the label input fires PATCH on every keystroke, the API receives a request per character typed. With a 500ms debounce or `onBlur` trigger, this is a non-issue. Without it, 10 keystrokes = 10 PATCH calls, each acquiring a DB pool connection. | **LOW** | Use `onBlur` (save on focus-leave) or a 500ms debounce. The PATCH itself is a fast single-row UPDATE — no cascading side effects — so duplicate calls are safe but wasteful. |

---

## Person Appearance Page

| # | Pitfall | Severity | Prevention |
|---|---------|----------|------------|
| A-1 | **N+1 DB queries from thumbnail URL pattern** — The existing `list_video_faces` and `list_video_detections` use `/frames/{frame_id}/image` as `thumbnail_url`. Each browser fetch for a thumbnail hits `GET /frames/{frame_id}/image`, which executes `SELECT minio_key FROM frames WHERE id = $1` + generates a presigned URL. A person appearance page with 30 videos × 3 thumbnail previews per video = 90 simultaneous browser requests, each acquiring a connection from the `max_size=10` asyncpg pool. 80 of those 90 requests will queue waiting for a pool slot. | **HIGH** | For the appearance page specifically, generate presigned URLs server-side in the aggregation response (like `list_video_detections` already does). This trades 90 browser→API round trips for one SQL aggregation query + N presigned URL calls (local HMAC, ~0.1ms each). Explicitly note this is the only endpoint that should embed presigned URLs — maintain the pattern from `storage.py`'s doc comment. |
| A-2 | **Aggregation query returns all rows, not grouped** — A naive implementation fetches every `face_detection` row for a person (potentially thousands) and groups them in Python. For a family member appearing in 200 videos at 10fps capture, this is ~2000+ rows fetched, deserialized, and grouped. The correct approach is a single SQL aggregation with `GROUP BY video_id` returning one row per video. | **HIGH** | Write a single aggregation query: `SELECT fr.video_id, MIN(f.ts_ms) AS first_ts, COUNT(fd.id) AS face_count, (SELECT id FROM frames f2 WHERE f2.video_id = fr.video_id ORDER BY fd2.det_score DESC LIMIT 1) AS rep_frame_id FROM face_detections fd JOIN frames fr ...`. Use a lateral join or subquery to pick the highest-`det_score` representative frame per video rather than fetching all rows. |
| A-3 | **Chronological sort requires `recorded_at`, which is nullable** — The feature calls for a "chronological appearance timeline." Sorting by `frames.ts_ms` gives within-video order only. Cross-video chronological order requires `videos.recorded_at`. This column is `NULLABLE` in the schema — cameras that don't embed timestamps leave it NULL. Sorting `ORDER BY v.recorded_at` puts all NULLs at top or bottom depending on sort direction, creating misleading timelines. | **MEDIUM** | Sort by `COALESCE(v.recorded_at, v.ingested_at)` and expose which field was used in the response (`"timeline_basis": "recorded_at" | "ingested_at"`). Warn in the UI when `recorded_at` is NULL ("Timeline based on upload order — camera timestamps unavailable"). |
| A-4 | **HNSW index interaction during concurrent clustering** — The appearance page query uses `WHERE fd.matched_person_id = $1`, which hits the B-tree index `face_detections (matched_person_id)` — not the HNSW index. However, `POST /cluster/run` does a bulk `UPDATE face_detections SET unknown_cluster_id = NULL` which takes a relation-level lock on `face_detections`. If a user opens the appearance page while clustering is running, the SELECT may block on the lock, causing a visible slowdown (seconds, not milliseconds). | **MEDIUM** | PostgreSQL's MVCC means the SELECT won't be blocked by a concurrent UPDATE unless the UPDATE takes an explicit lock. In practice, the bulk UPDATE in `run_clustering` uses no explicit lock — MVCC reads proceed. Flag as "monitor but likely fine." If slowness is observed, add a `statement_timeout` on the appearance page query. |
| A-5 | **Presigned URLs embedded in JSON expire after 1 hour** — If the person appearance page returns presigned frame thumbnail URLs in the JSON body (recommended above to avoid N+1), React Query or the browser may cache the page result. After 1 hour the thumbnails will return 403. The React frontend currently uses these URLs directly (e.g., `<img src={thumbnailUrl} />`). | **MEDIUM** | Set React Query `staleTime` for appearance page queries to at most 50 minutes (under the 1-hour TTL). The default staleTime is 0, meaning every page load re-fetches — which actually avoids this issue by default. Add a comment in the React component: `// staleTime must be < presigned URL TTL (3600s = 3600000ms)`. |
| A-6 | **`person_id` 404 during concurrent delete** — If a person is deleted (`DELETE /persons/{id}`) while the appearance page is loading, the appearance query returns 0 rows (cascade NULLs `matched_person_id`). A half-loaded React page may show an empty list with no explanation. | **LOW** | Return 404 from the appearance endpoint if the `known_persons` row no longer exists (single `SELECT 1 FROM known_persons WHERE id = $1` preflight, which already exists in `list_person_faces`). The React page should handle 404 with "Person not found" rather than an empty table. |

---

## Watch-Folder Auto-Ingest

| # | Pitfall | Severity | Prevention |
|---|---------|----------|------------|
| W-1 | **File still being written when watchdog fires** — `FileCreatedEvent` (and `FileModifiedEvent`) fire when the OS creates or modifies the file inode — not when the write is complete. For a 1GB video being copied from NAS to the watch folder, watchdog fires seconds before the copy finishes. Uploading a partially-written file to MinIO produces a truncated video; FFmpeg then fails to extract frames, setting `status='failed'` in the DB. The file is permanently broken unless manually force-re-ingested. | **CRITICAL** | Use inotify `IN_CLOSE_WRITE` semantics: watchdog's `on_closed()` handler (available in watchdog ≥ 3.0) fires only after the file handle is closed. Fallback for watchdog < 3.0: poll file size twice with a 2-second sleep — if size is stable, proceed. Add a minimum file size guard (reject files < 10KB as likely truncated). |
| W-2 | **inotify does not work on NFS/SMB mounts** — If the watch folder is on a network-attached NAS mounted via NFS or CIFS into the Docker host (or into the container via volume mount), inotify events are NOT delivered by the kernel. Watchdog silently falls back to polling (OS X Observer or Polling Observer), which checks every second but may miss rapid changes. The failure mode is: events fire on ext4/btrfs but never fire on NFS. | **HIGH** | Explicitly configure the daemon with `watchdog.observers.polling.PollingObserver` when the watch path is known to be a network mount, or always use polling for safety. Add a startup check: log which observer class is active. Document in `.env.example` that `WATCH_USE_POLLING=true` must be set for NFS/CIFS paths. |
| W-3 | **No persistent state — files dropped while daemon is down are missed** — Watchdog does not persist event history. If the watch-daemon container restarts (crash, `docker-compose restart`), any files dropped during downtime are invisible to the daemon — no `FileCreatedEvent` fires for them because they already exist. | **HIGH** | Add a **startup scan**: on container start, walk the watch folder and call `POST http://ingestion-worker:8001/ingest` for every file found. The existing ingest endpoint returns `status: "skipped"` for already-done videos at near-zero cost (`SELECT id, status FROM videos WHERE minio_key = $1`). This startup scan costs one DB query per file and closes the missed-event gap entirely. |
| W-4 | **Queue saturation causes OOM on 8GB system** — The ingestion worker uses FastAPI `BackgroundTasks` with NO concurrency limit. If the daemon submits 10 files in rapid succession, 10 `process_video()` coroutines start concurrently. Each YOLO inference uses ~1.5GB RAM; each InsightFace run uses ~2GB. Two concurrent pipelines = ~7GB, leaving 1GB for the OS. Three concurrent pipelines = OOM kill. The worker has a `memory: 5g` Docker limit — it will be killed and restart mid-pipeline, corrupting `status='processing'` videos that never recover (mitigated by `reset_stale_processing_videos` on startup, but videos are lost). | **CRITICAL** | Add a `asyncio.Semaphore(1)` (or configurable `MAX_CONCURRENT_INGEST=1`) in the ingestion worker to limit concurrent `process_video` calls. The watch daemon should also rate-limit: submit one file, optionally wait for completion or add a fixed delay (e.g., 30 seconds between submissions). Document that `MAX_CONCURRENT_INGEST` must be 1 on this hardware. |
| W-5 | **MinIO key collision on same filename** — The watch daemon uploads files to MinIO with key `videos/{filename}`. If two files named `camera_front.mp4` are dropped on different days, the second upload silently overwrites the first in MinIO. The first video's DB row (`videos.minio_key = 'videos/camera_front.mp4'`) now points to the wrong video bytes. The `videos.minio_key UNIQUE` constraint prevents a second DB row, so the second ingest call returns `status: "skipped"`. Result: the second file is permanently lost. | **HIGH** | Generate unique keys: `videos/{YYYYMMDD_HHMMSS}_{filename}` or `videos/{uuid4()}_{filename}`. The watch daemon controls the upload key — it should not reuse the existing `POST /videos/upload-url` endpoint (which uses basename only). Alternatively, check if the key already exists in MinIO before upload and add an incrementing suffix. |
| W-6 | **Race: MinIO upload succeeds, ingest call fails** — The daemon uploads to MinIO then calls `POST /ingest`. If the ingest call fails (worker temporarily down, network blip), the file exists in MinIO but has no DB record. On daemon restart, the startup scan (#W-3) rescues this: it walks the watch folder and re-calls `POST /ingest`, which will create the DB record and queue processing. Without the startup scan, this race creates permanently orphaned MinIO objects. | **MEDIUM** | The startup scan (W-3 prevention) also mitigates W-6. No additional fix needed if W-3 is implemented correctly. |
| W-7 | **`on_moved` events missed (rsync, mv, atomic renames)** — Applications like `rsync --in-place` or any copy-then-rename strategy create a temp file then atomically rename it to the final name. Watchdog fires `FileMovedEvent`, NOT `FileCreatedEvent`, for the rename step. A daemon that only implements `on_created` silently ignores rsync-deposited files. | **MEDIUM** | Implement both `on_created` and `on_moved` in the watchdog `FileSystemEventHandler`. In `on_moved`, treat `event.dest_path` as the new file to ingest (same logic as `on_created`). Also ignore events where `dest_path` is a temp file (starts with `.` or ends with `.tmp`/`.part`). |
| W-8 | **Docker volume mount — UID/GID permission mismatch** — The watch-daemon container runs as a non-root user (or root, depending on Dockerfile). The files written to the watch folder by an external process (camera NVR software, `rsync` daemon, another container) may be owned by a different UID. The daemon can `os.path.exists()` the file (directory is readable) but fails on `open(path, 'rb')` with `PermissionError`. This is hard to debug because `stat` shows the file exists. | **MEDIUM** | In docker-compose.yml, set `user: "${UID}:${GID}"` on the watch-daemon service and ensure the host watch folder has group-read permissions (`chmod g+r`). Or run the daemon as root within its container (acceptable for a homeserver where the single user IS root). Add explicit permission check on startup: `os.access(watch_path, os.R_OK)` and fail fast with a clear error message. |
| W-9 | **`home-infra` external network must pre-exist** — The docker-compose.yml declares `networks: home-infra: external: true`. The watch-daemon service must also join this network. If the network doesn't exist at `docker-compose up` time, Docker logs a confusing error: `network home-infra declared as external, but could not be found`. This error is easy to hit when first deploying the daemon on a fresh machine or after a Docker reset. | **LOW** | Add network creation to the deployment runbook: `docker network create home-infra` before `docker-compose up`. The network already exists in production but must be documented for future deploys. |
| W-10 | **Ingestion worker endpoint address** — The watch daemon calls the ingestion worker at `http://ingestion-worker:8001/ingest` (internal Docker network). The nginx proxy exposes this as `/ingest-api/ingest` to browsers. The daemon should use the DIRECT internal address (`ingestion-worker:8001`), not the nginx proxy path. Using the nginx proxy path adds an unnecessary hop and CORS/auth complications. | **LOW** | Hardcode `INGEST_WORKER_URL=http://ingestion-worker:8001` in the daemon's environment config. Never use the public `INGEST_API_URL`. The worker has no auth on its `/ingest` endpoint currently — verify this is acceptable for an internal-only service (it is, since port 8001 is not exposed externally in docker-compose.yml). |

---

## Cross-Cutting Concerns

### XC-1: Schema Migration Convention Must Be Followed

**What:** All v1.x DB changes used numbered SQL files in `db/migrations/` (001, 002, 003). There is NO Alembic — migrations are applied manually. If a developer adds a column in the wrong migration file, runs a migration twice, or adds a column without `IF NOT EXISTS`, it breaks the production DB on apply.

**Prevention:** Any v2.0 schema change (e.g., adding a constraint, index, or new column) must be in `db/migrations/004_*.sql` with `IF NOT EXISTS` guards. The label column itself already exists — **no migration needed for feature L** unless adding a constraint. If adding an index on `unknown_clusters (label)` for search, write it as:
```sql
CREATE INDEX IF NOT EXISTS unknown_clusters_label_idx ON unknown_clusters (label);
```

---

### XC-2: `asyncpg` Pool Exhaustion Under Combined Load

**What:** The API service pool has `max_size=10`. During watch-folder ingest, the ingestion worker is running `process_video` (its own pool, max_size=10 from `ingestion-worker/app/db.py`). Simultaneously, if the user opens the person appearance page with many thumbnails loading, the API pool can be saturated. Symptoms: requests queue behind pool acquisition and `/health` check latency spikes.

**Risk mapping:**
- Person appearance page: 1 connection for the aggregation query + potentially N connections for `/frames/{id}/image` thumbnail loads if not using embedded presigned URLs.
- Watch-daemon ingest: connections on the ingestion-worker pool (separate), not the API pool.
- Combined: only a concern if the user is actively browsing while ingest is running.

**Prevention:** Implement the server-side presigned URL embedding on the appearance page (see A-1). This reduces per-page API pool usage from N (one per thumbnail) to 1 (the aggregation query).

---

### XC-3: Clustering Re-Run Clobbers `unknown_cluster_id` on ALL Unmatched Faces

**What:** Step 6 of `run_clustering()` (line 256 of `clustering.py`) runs:
```sql
UPDATE face_detections SET unknown_cluster_id = NULL WHERE matched_person_id IS NULL
```
This clears ALL cluster assignments before re-assigning. This runs as part of the nightly n8n cron. Any labeled cluster whose faces are re-clustered into a different UUID loses its label association. This is not new for v2.0, but label nicknames make the consequence visible to users for the first time.

**Prevention:** The label is on the `unknown_clusters` row, not on `face_detections`. The cluster row persists (unless no faces are assigned). The risk is UUID drift (see L-3), not this step directly. However: if the nightly run runs during a user labeling session, the label survives but the cluster's membership may change, making the label misleading ("Delivery Guy" cluster now contains faces that look different).

**Mitigation:** Add a log entry after clustering that lists clusters with non-null labels and their new appearance_count, so the user can verify label validity.

---

### XC-4: Sequential ML Models Must Remain Sequential — Watch Daemon Must Not Trigger This

**What:** The pipeline constraint (`pipeline.py` header comment: "YOLO and InsightFace NEVER run in parallel — sequential only (memory constraint)") is currently enforced implicitly by the single-threaded nature of background task execution for one video. The watch daemon, by submitting multiple ingest requests rapidly, is the first mechanism that can break this invariant.

**Prevention:** This is the same as W-4 (semaphore). Restating here because it is a *design principle violation* if concurrent pipelines run, not just an OOM risk. The semaphore must be added to `process_video` before the watch daemon goes live.

---

### XC-5: No Auth on Ingestion Worker Endpoint

**What:** `POST /ingestion-worker:8001/ingest` has NO bearer token check (the API service has auth; the ingestion worker does not based on `main.py`). The nginx proxy exposes `/ingest-api/` publicly (port 80), forwarding the `Authorization` header but not validating it in the worker. The watch daemon calling the worker directly over the Docker internal network bypasses any nginx-level auth.

**Risk:** Low for a single-user homeserver — the ingestion worker port (8001) is not exposed externally in docker-compose.yml. But if the server is ever misconfigured (e.g., `ports: "8001:8001"` accidentally added), the ingest endpoint becomes unauthenticated internet-accessible.

**Prevention:** Keep port 8001 as internal-only (no `ports:` mapping for ingestion-worker in docker-compose — it currently has one: `"${WORKER_PORT:-8001}:8001"`). The watch daemon should use the internal Docker DNS name. If adding auth to the worker is desired, it can reuse the same `API_TOKEN` environment variable, but this is optional for v2.0.

---

## Phase Recommendations (for Roadmapper)

| Phase Topic | Most Critical Pitfall | Must-Address Before |
|-------------|----------------------|---------------------|
| Cluster labeling PATCH endpoint | L-1 (column name collision), L-2 (GET response missing label) | Before UI work begins |
| Person appearance page query | A-1 (N+1 thumbnails), A-2 (naive aggregation) | Before frontend page built |
| Person appearance page frontend | A-5 (presigned URL TTL + React Query staleTime) | Before testing |
| Watch daemon — file stability | W-1 (partial file copy) | Before any file is ever ingested by daemon |
| Watch daemon — concurrency | W-4 (OOM from concurrent pipelines) | Before daemon goes live |
| Watch daemon — deployment | W-3 (startup scan), W-5 (key collision), W-7 (on_moved) | Before daemon runs in production |
| All features | XC-1 (migration convention) | Before any DB change is committed |
| Watch daemon + any concurrent use | XC-4 (sequential ML invariant) | Before watch daemon submits first file |
