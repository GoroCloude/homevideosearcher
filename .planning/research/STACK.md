# Stack Research: HomeVideoSearcher

**Researched:** 2025-05-15  
**Mode:** Validation — fixed stack confirmed against current (2025) ecosystem  
**Overall Confidence:** HIGH (all choices verified against PyPI, Docker Hub, Context7 docs)

---

## Validated Stack Choices

### 1. Object Detection — YOLOv8 via Ultralytics ✅ (with upgrade note)

**Status: VALID, but YOLO11n is a better drop-in for new projects.**

- `ultralytics==8.4.51` (latest, May 2025) supports both `yolov8n.pt` **and** `yolo11n.pt` from the same API — zero code change required to switch.
- YOLO11 is now Ultralytics' **featured model**: YOLO11m achieves higher mAP than YOLOv8m with **22% fewer parameters** (Context7 confirmed). The nano variant (YOLO11n) follows the same efficiency pattern.
- YOLOv8n (the one in requirements.md) is still **fully supported, downloads correctly, and is not deprecated**. It remains a safe choice.
- **Recommendation for this project:** Start with `yolov8n.pt` as specified. The requirements performance targets (≤ 0.3 s/frame) are achievable with YOLOv8n. Upgrade to `yolo11n.pt` only if accuracy on home-camera footage proves insufficient — it's a one-line change.
- **Do NOT use OpenVINO** in v1: OpenVINO can give ~2–3× speedup on Intel CPUs (confirmed in docs) but adds build complexity, a larger Docker image, and the i5-6200's CPU-only path is sufficient for batch processing. Flag as a future optimization.

```python
from ultralytics import YOLO
model = YOLO("yolov8n.pt")   # v1
# model = YOLO("yolo11n.pt") # v2 upgrade, zero API change
```

**Confidence:** HIGH — verified against Ultralytics GitHub + Context7 docs.

---

### 2. Face Detection + Recognition — InsightFace `buffalo_l` ✅ (with maintenance flag)

**Status: VALID — still the correct choice for CPU face recognition in 2025. Flag: slow release cadence.**

- `insightface==0.7.3` (PyPI, latest). **GitHub last release: v0.7 (Feb 2023).** No new PyPI release in 2+ years.
- Despite the slow release cadence, the library is **stable and functional**: SCRFD detector + ArcFace 512-dim embeddings remain state-of-the-art for CPU-side face recognition. No credible open-source CPU replacement has emerged.
- `buffalo_l` model pack: SCRFD-10G face detector + R100 ArcFace. This is the **accuracy tier** — slower but more precise. For a batch system (not real-time), this is the correct choice.
- `buffalo_s` exists as a faster/lighter alternative if the `buffalo_l` inference budget (≤ 1.0 s/frame) proves too slow, but the requirements already account for `buffalo_l` timing.
- `normed_embedding` is L2-normalized out of the box — **do not re-normalize**, just store directly as `vector(512)`.
- The cosine similarity threshold of `0.5` (from requirements) is appropriate for ArcFace embeddings. Consider tuning to `0.45`–`0.55` range based on real-world enrollment images.

```python
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=0, det_size=(640, 640))
```

**Alternatives considered and rejected:**
- **DeepFace**: Higher-level wrapper; less control over embedding pipeline; slower.
- **FaceNet (facenet-pytorch)**: GPU-oriented, CPU performance worse than InsightFace ArcFace.
- **face_recognition (dlib)**: Older 128-dim Dlib model; lower accuracy than ArcFace on family-scale datasets.

**Confidence:** HIGH for current functionality; MEDIUM for long-term maintenance (upstream activity is low).

---

### 3. Vector Database — PostgreSQL 16 + pgvector ✅

**Status: VALID — still the right choice for a self-hosted single-node system.**

- Docker image: `pgvector/pgvector:pg16` — **latest tag is `0.8.2-pg16`** (Docker Hub, May 2025). Requirements.md uses `pgvector/pgvector:pg16` which resolves to this.
- Python client: `pgvector==0.4.2`.
- **HNSW index** (as specified in requirements.md schema) is the correct index type for 512-dim cosine search. IVFFlat is faster to build but requires knowing vector count in advance; HNSW is better for a growing home dataset.
- pgvector 0.8.x added `halfvec` (float16 storage) — could halve embedding storage (512 × 2 bytes = 1 KB/embedding vs 2 KB). Not needed for v1 (even 100K frames × 3 faces = 300 MB, trivial). Worth knowing for future.
- **No better alternative for this use case**: Qdrant/Weaviate/Milvus add operational complexity with no benefit at home-video scale. pgvector co-locating vectors with relational data is the key advantage here (single JOIN for filtering by person + date + class).

```sql
-- Already in requirements.md schema — confirmed correct
CREATE INDEX ON face_detections USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON person_embeddings USING hnsw (embedding vector_cosine_ops);
```

**Confidence:** HIGH — verified against pgvector GitHub (v0.8.2), Docker Hub, Context7 docs.

---

### 4. Backend API — FastAPI + asyncpg ✅

**Status: VALID — idiomatic 2025 Python ML-serving stack.**

- `fastapi==0.136.1` (latest, PyPI). Very active development (confirmed against GitHub releases).
- `asyncpg==0.31.0` (latest, PyPI). The correct async PostgreSQL driver for FastAPI/asyncio.
- **Use `asyncpg` directly** (as implied by requirements.md `db.py`), not SQLAlchemy ORM. For this use case (mostly hand-written SQL with pgvector operators), raw asyncpg is faster and simpler.
- `BackgroundTasks` (FastAPI built-in) is correct for v1 ingestion triggering. Do NOT add Celery in v1 — adds Redis dependency and operational complexity with no benefit for a single-job queue.
- **`python-multipart`** is required for file upload endpoints (enroll images) — add to requirements.txt.
- Pydantic v2 is the default in FastAPI 0.100+. Use `model_config = ConfigDict(...)` not `class Config`.

```python
# Confirmed idiomatic pattern
from fastapi import FastAPI, BackgroundTasks
import asyncpg

pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=2, max_size=10)
```

**Confidence:** HIGH — verified against FastAPI GitHub + Context7 docs.

---

### 5. ONNX Runtime — CPU Inference ✅

**Status: VALID.**

- `onnxruntime==1.26.0` (PyPI latest). Both InsightFace and Ultralytics use ONNX Runtime for CPU inference.
- Install `onnxruntime` (CPU-only), **not** `onnxruntime-gpu`. The GPU variant does not degrade gracefully on CPU-only hosts.
- Set `OMP_NUM_THREADS=4` (as in requirements.md) — correct for i5-6200 (dual-core, 4 threads). Prevents ONNX from spawning too many threads and thrashing.

**Confidence:** HIGH.

---

### 6. Object Storage Client — MinIO (boto3 / minio-py) ✅

**Status: VALID.**

- `minio==7.2.20` (PyPI latest). The Minio Python SDK is actively maintained.
- Alternatively, `boto3` works against MinIO (S3-compatible). MinIO's own SDK is lighter; prefer it.
- Presigned URL generation (for video streaming and frame thumbnails) works correctly with both.

**Confidence:** HIGH.

---

### 7. Frontend — React 18 + Vite + TypeScript + TanStack Query ✅

**Status: VALID.**

- React 18 + Vite + TypeScript — standard 2025 SPA stack. No concerns.
- `@tanstack/react-query` v5 (TanStack Query) — current major version. API changed from v4: `useQuery({ queryKey, queryFn })` (object form only). Verify v5 syntax if copying v4 examples.
- Tailwind CSS v4 is now released (breaking changes from v3 in configuration). Pin to **Tailwind v3** for v1 to avoid migration friction, or use v4 if starting fresh (no existing config).

**Confidence:** HIGH for core stack; MEDIUM for Tailwind version choice (pin explicitly).

---

### 8. Python Dependency Management — uv ✅

**Status: VALID — preferred choice in 2025.**

- `uv==0.11.14` (latest). uv is now the de facto fast Python package manager. Much faster than pip for Docker builds. Actively maintained by Astral.
- Use `uv pip compile requirements.in > requirements.txt` to pin. Or use `uv` with `pyproject.toml` + lockfile.

**Confidence:** HIGH.

---

## Unknown Face Clustering (New)

**Recommendation: HDBSCAN via scikit-learn built-in (sklearn ≥ 1.3)**

### Why HDBSCAN, not DBSCAN

| Property | DBSCAN | HDBSCAN |
|---|---|---|
| Requires `epsilon` tuning | Yes — hard to set right for face embeddings | No — only `min_cluster_size` |
| Handles noise (solo faces) | Yes (`-1` label) | Yes (`-1` label) — better |
| Variable cluster density | Struggles | Handles naturally |
| Cluster stability | Can split/merge on epsilon | Stable hierarchy |
| Library needed | `scikit-learn` (built-in) | `scikit-learn ≥ 1.3` (built-in since 1.3) |

scikit-learn 1.8.0 (current) ships `sklearn.cluster.HDBSCAN` natively — **no extra dependency**.

### Recommended Approach

```python
import numpy as np
from sklearn.cluster import HDBSCAN

# Query: all face_detections where matched_person_id IS NULL
# embeddings: np.array, shape (N, 512), already L2-normalized

clusterer = HDBSCAN(
    min_cluster_size=3,       # A "stranger" must appear in ≥ 3 frames to form a cluster
    min_samples=2,            # Core point density — be lenient for sparse home footage
    metric="cosine",          # Correct for ArcFace embeddings
    cluster_selection_epsilon=0.0,
)
labels = clusterer.fit_predict(embeddings)  # -1 = noise (isolated face, ignore)

# labels[i] = cluster ID → "Unknown Person 0", "Unknown Person 1", ...
# Store results in a new table: unknown_person_clusters
```

### Schema addition (new table for v1)

```sql
CREATE TABLE unknown_clusters (
    id          SERIAL PRIMARY KEY,
    label       INT NOT NULL,                    -- HDBSCAN cluster label
    name        TEXT,                             -- user-assigned later ("Delivery person")
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE face_detections 
    ADD COLUMN unknown_cluster_id INT REFERENCES unknown_clusters(id) ON DELETE SET NULL;
```

### Workflow

1. **Batch job** (nightly, separate from ingestion): query all `unknown` face embeddings, run HDBSCAN, upsert cluster assignments.
2. **Stability**: Between runs, use centroid matching (cosine nearest-neighbor) to map new cluster IDs to existing known clusters, avoiding relabel churn.
3. **User action**: Search UI shows "Unknown Persons" section with cluster thumbnails; user can name them or promote to `known_persons` + re-enroll via existing `/persons` API.

### Parameters to configure via ENV

```
CLUSTER_MIN_SIZE=3          # Min frames to form a cluster (default 3)
CLUSTER_MIN_SAMPLES=2       # HDBSCAN min_samples (default 2)
```

**Confidence:** HIGH — HDBSCAN cosine clustering for face embeddings is well-established in the literature and production systems. scikit-learn 1.8.0 confirmed.

---

## Flags / Concerns

### 🔴 Critical

**None** — the stack is sound for the described use case.

---

### 🟡 Important

**1. InsightFace maintenance lag**  
Last release: Feb 2023 (v0.7). The library is effectively in maintenance mode. It continues to work, but:
- Python 3.12+ compatibility may break without patches (test explicitly on 3.11 as specified — Python 3.11 is fine)
- No new models will come from this upstream
- **Mitigation**: Pin `insightface==0.7.3`, test on Python 3.11 (not 3.12), use the ONNX backend (CPUExecutionProvider) which is stable

**2. Memory is tight — sequential processing is mandatory**  
YOLO (~500 MB) + InsightFace buffalo_l (~1.5 GB) + PostgreSQL (~1 GB) + OS (~2 GB) = ~5 GB active.  
At 8 GB total:
- **Never load both YOLO and InsightFace at startup simultaneously if possible** — load each before its pipeline step, or keep both warm but keep frame batches tiny (1–4 frames)
- Add a 4 GB swap file on the host as a safety net
- Set `ONNX_DISABLE_GLOBAL_THREAD_POOL=1` alongside `OMP_NUM_THREADS=4` to prevent thread oversubscription
- Docker `memory: 5g` limit on ingestion-worker (as in requirements.md) is correct

**3. YOLO11n upgrade path**  
YOLO11n is strictly better than YOLOv8n (higher mAP, fewer params, same COCO classes, same API). Since the stack is not locked to a specific YOLO version number for any integration reason, consider switching in v1 before releasing. Change: `YOLO_MODEL=yolo11n.pt` in `.env`.

**4. Tailwind v3 vs v4**  
Tailwind CSS v4 was released with significant config-file changes. If starting fresh, choose **one** and pin. Mixing Tailwind v3 docs with v4 installation causes subtle breakage.

---

### 🟢 Low Concern

**5. pgvector `halfvec` — not needed yet**  
For a home system (realistic: <500K face detections), full `vector(512)` is fine. If the library grows to millions of rows, `halfvec(512)` is a transparent upgrade with half the index memory.

**6. asyncpg vs psycopg3**  
psycopg3 now supports async and pgvector. It is not meaningfully better for this use case. asyncpg is faster for high-concurrency, but for a single-user API, the difference is negligible. Stick with asyncpg (it's in the requirements and asyncpg has first-class pgvector support via `pgvector==0.4.2`).

**7. n8n MinIO event trigger reliability**  
n8n's S3/MinIO trigger node requires MinIO webhook configuration. If MinIO events prove unreliable, fall back to the scheduled scan (every 10 min poll `GET /videos?status=pending`). Build both paths.

---

## Versions (Pinned Recommendations)

| Package | Pinned Version | Notes |
|---|---|---|
| `ultralytics` | `==8.4.51` | Supports both yolov8n.pt and yolo11n.pt |
| `insightface` | `==0.7.3` | Last stable; pin tightly |
| `onnxruntime` | `==1.26.0` | CPU-only build |
| `fastapi` | `==0.136.1` | Pydantic v2 API |
| `pydantic` | `>=2.0,<3` | Comes with FastAPI |
| `uvicorn[standard]` | `>=0.34` | ASGI server |
| `asyncpg` | `==0.31.0` | PostgreSQL async driver |
| `pgvector` | `==0.4.2` | Python pgvector client |
| `python-multipart` | `>=0.0.20` | Required for file upload |
| `minio` | `==7.2.20` | MinIO Python SDK |
| `scikit-learn` | `==1.8.0` | Includes HDBSCAN natively |
| `numpy` | `>=1.26,<3` | InsightFace + sklearn compatibility |
| `opencv-python-headless` | `>=4.10` | Frame processing (no GUI deps) |
| `uv` | `0.11.14` | Package manager (host tool, not in requirements.txt) |

**Docker Images:**

| Image | Tag | Notes |
|---|---|---|
| `pgvector/pgvector` | `0.8.2-pg16` | Pin exact version, not `pg16` floating tag |
| `python` | `3.11-slim-bookworm` | Confirmed InsightFace + ONNX compatible |
| `node` | `22-alpine` | Vite build |
| `nginx` | `1.27-alpine` | Serve static React build |

---

## Sources

- Ultralytics GitHub releases: https://github.com/ultralytics/ultralytics/releases (verified v8.4.51, May 2025)
- Ultralytics YOLO11 docs: https://github.com/ultralytics/ultralytics/blob/main/docs/en/models/yolo11.md (Context7)
- InsightFace PyPI: https://pypi.org/project/insightface/ (v0.7.3, last release 2023)
- pgvector Docker Hub: https://hub.docker.com/r/pgvector/pgvector/tags (0.8.2-pg16, May 2025)
- pgvector README: https://github.com/pgvector/pgvector/blob/master/README.md (Context7, v0.8.2)
- FastAPI GitHub: https://github.com/fastapi/fastapi/releases (v0.136.1)
- scikit-learn: https://pypi.org/project/scikit-learn/ (v1.8.0, HDBSCAN built-in since 1.3)
- asyncpg: https://pypi.org/project/asyncpg/ (v0.31.0)
- onnxruntime: https://pypi.org/project/onnxruntime/ (v1.26.0)
- minio: https://pypi.org/project/minio/ (v7.2.20)
- uv: https://pypi.org/project/uv/ (v0.11.14)

---

# Stack Research — v2.0

**Milestone:** v2.0 Smart Labels, Person Pages & Auto-Ingest  
**Researched:** 2026-05-22  
**Scope:** ADDITIONS ONLY — do not re-research the validated v1.x stack above.  
**Confidence:** HIGH (verified against PyPI, Context7 watchdog docs, live schema inspection)

---

## New Dependencies

| Feature | Package | Version | Reason |
|---------|---------|---------|--------|
| Watch-folder daemon | `watchdog` | `6.0.0` | Filesystem event monitoring on Linux via inotify kernel API. Pure-Python, well-maintained, ships `InotifyObserver` (event-driven, zero polling). Latest as of 2026-05. |
| Watch-folder daemon | `requests` | `>=2.32` | Simple sync HTTP to call `POST /ingest` on the ingestion-worker. Watchdog event handlers run in OS threads (not async), so a synchronous HTTP client is the correct fit. Already a transitive dep in the Python ecosystem; no weight added. |

> `minio==7.2.20` is already a dependency of both `api` and `ingestion-worker`. The new `watch-folder` service reuses the same version — no version conflict.

---

## No New Dependencies Needed

### Feature 1 — Cluster nickname labeling

- **DB schema:** `label TEXT` column already exists in `unknown_clusters` in `001_schema.sql` (line 84). No migration file needed.  
- **API:** Needs a `PATCH /clusters/{id}/label` endpoint and `label` field added to `ClusterResponse`. Pure Python — no new packages.  
- **React UI:** Inline text input wired to a TanStack Query `useMutation`. `@headlessui/react` (already installed) covers the editable field pattern. No new npm package.

### Feature 2 — Person appearance page (`/people/:id`)

- **Routing:** `react-router-dom 6.30.1` already installed — add a `<Route path="/people/:id" />`.  
- **Data fetching:** TanStack Query v5 already installed — one new `useQuery` call.  
- **Date/time formatting:** `date-fns 4.1.0` already installed — covers timestamp display.  
- **Thumbnails:** presigned URL pattern already implemented in `GET /frames/:id/image` — reuse directly.  
- **No new npm or Python packages required.**

### Feature 3 — Watch-folder daemon (React/UI side)

No UI changes required. The watch-folder service is entirely backend. Users drop files into a folder on the homeserver; the pipeline is invisible.

---

## Migration Notes

**No new migration file is needed for v2.0.**

`label TEXT` was included in the initial schema (`db/init/001_schema.sql`, `unknown_clusters` table). The existing `ON CONFLICT DO UPDATE` in `POST /cluster/run` deliberately omits `label` from the update clause, so re-running clustering preserves user-assigned labels. The column is live in all environments.

**Migration pattern to maintain:** The project uses hand-written numbered SQL files (`db/migrations/NNN_*.sql`) applied manually (not Alembic). Do NOT introduce Alembic for v2.0 — it would add SQLAlchemy as a dependency and require model mirroring for a codebase that uses raw asyncpg. The plain-SQL pattern is correct for this project size.

---

## Watch-Folder Library Decision

### Options evaluated

| Library | Mechanism | Linux support | Docker bind-mount safe | Complexity |
|---------|-----------|--------------|----------------------|------------|
| `watchdog` (InotifyObserver) | inotify kernel API — event-driven | ✅ Native | ✅ Yes — inotify works on host kernel; events propagate to container | Low (high-level API) |
| `inotify-simple` / `inotify` | Raw inotify syscall bindings | ✅ Native | ✅ Yes | High (manual fd management, no handler pattern) |
| `watchdog` (PollingObserver) | Periodic `os.stat` scan | ✅ Any OS | ✅ Yes (but also works on NFS/SMB) | Low |
| Pure polling loop (manual) | `os.listdir` + sleep | ✅ Any OS | ✅ Yes | Medium (must track seen files, race conditions) |

### Recommendation: `watchdog 6.0.0` with `InotifyObserver`

**Why watchdog over inotify-simple:**  
`inotify-simple` requires manual file-descriptor management, event-loop integration, and path reconstruction. `watchdog` wraps all of this into a clean `FileSystemEventHandler` subclass. For a daemon that calls one HTTP endpoint on file creation, the low-level API adds no value.

**Why InotifyObserver over PollingObserver:**  
The homeserver is Ubuntu Linux — inotify is available and efficient. Polling burns CPU checking for changes every N seconds and adds latency. InotifyObserver fires within milliseconds of a kernel-level close event. Use `PollingObserver` only if the watch directory is on a network share (NFS/SMB) where inotify does not propagate.

**Critical inotify subtlety — use `on_closed()` not `on_created()`:**  
When a large video file is copied into the watch folder, `FileCreatedEvent` fires the moment the file appears — before the copy completes. Attempting to upload a partial file to MinIO produces a corrupted object. On Linux, watchdog maps `IN_CLOSE_WRITE` (inotify kernel event fired when the last write FD is closed) to `FileClosedEvent`, handled via `on_closed()`. This is the correct trigger for a watch-folder use case. Verified in Context7 watchdog docs — `on_closed()` is a supported handler method.

```python
from watchdog.observers.inotify import InotifyObserver
from watchdog.events import FileSystemEventHandler, FileClosedEvent

class VideoDropHandler(FileSystemEventHandler):
    def on_closed(self, event: FileClosedEvent) -> None:
        # File is fully written — safe to upload
        if not event.is_directory:
            upload_and_ingest(event.src_path)

observer = InotifyObserver()
observer.schedule(VideoDropHandler(), path="/watch", recursive=False)
observer.start()
```

**Docker bind-mount behavior:**  
inotify operates at the Linux kernel level. When the host directory is bind-mounted into the container (`volumes: - /srv/video-drop:/watch`), inotify events generated by writes on the host ARE visible inside the container because they share the same kernel. Confirmed behavior on Linux Docker host — no special configuration needed.

**inotify watch limit:**  
Default Linux kernel limit: 8192 watches per user (each watched directory = 1 watch). With `recursive=False` (single flat directory), this consumes exactly 1 watch. Not a concern for this project.

### Implementation summary for the new service

```
services/watch-folder/
  Dockerfile          # python:3.11-slim, installs watchdog + minio + requests
  app/
    main.py           # InotifyObserver loop; uploads to MinIO; POSTs /ingest
    config.py         # WATCH_DIR, MINIO_*, WORKER_URL env vars
  requirements.txt    # watchdog==6.0.0, minio==7.2.20, requests>=2.32, python-dotenv>=1.0
```

Docker Compose addition:
```yaml
watch-folder:
  build: ./services/watch-folder
  volumes:
    - /srv/video-drop:/watch   # host path bind-mounted read-write
  environment:
    WATCH_DIR: /watch
    MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
    MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
    MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
    MINIO_BUCKET_VIDEOS: ${MINIO_BUCKET_VIDEOS:-videos}
    WORKER_URL: http://ingestion-worker:8001
  depends_on:
    - ingestion-worker
  networks:
    - home-infra
```

No `memory` limit override needed — watchdog + requests is ~30 MB RSS.

---

## Sources

- watchdog 6.0.0: https://pypi.org/project/watchdog/ (latest confirmed 2026-05)
- watchdog docs (Context7, HIGH confidence): `/gorakhargosh/watchdog` — InotifyObserver, FileClosedEvent, on_closed() handler all verified
- `unknown_clusters.label` column: `db/init/001_schema.sql` line 84 (direct inspection, HIGH confidence)
- requests 2.34.x: https://pypi.org/project/requests/
- inotify kernel docs: https://man7.org/linux/man-pages/man7/inotify.7.html
