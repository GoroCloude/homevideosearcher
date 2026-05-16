# Architecture Research: HomeVideoSearcher

**Domain:** Self-hosted, CPU-only video analytics with face recognition  
**Researched:** 2025-05-16  
**Confidence:** HIGH — requirements.md provides detailed baseline; research verifies/extends with HDBSCAN, MinIO streaming, memory, and new components

---

## Component Map (Updated)

The requirements.md defines a 4-service stack. Two new components are required for v1 clustering and Telegram digest.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Existing Infra (external)                        │
│   MinIO (videos/ frames/ enrollment/)   n8n   Cloudflare Tunnel          │
└──────────┬──────────────────────────┬──────────────────────────────────-┘
           │ object events / HTTP      │ cron + HTTP POSTs
           ▼                          ▼
┌────────────────────────┐   ┌────────────────────────────────────────────┐
│  ingestion-worker      │   │  api (FastAPI)                              │
│  FastAPI + Background  │   │  - /videos, /search, /persons, /frames     │
│  Tasks                 │   │  - /ingest (trigger ingestion-worker)      │
│  - FFmpeg extraction   │   │  - /stream → 302 presigned MinIO URL       │
│  - YOLOv8n detection   │   │  - POST /cluster/run  ← NEW               │
│  - InsightFace embed   │   │  - GET  /digest/preview ← NEW             │
│  - pgvector matching   │   │  - Telegram send via python-telegram-bot   │
│  Memory limit: 5 GB    │   └──────────────────┬─────────────────────────┘
└────────────────────────┘                      │
           │                                    │
           └──────────────┬─────────────────────┘
                          ▼
           ┌────────────────────────────────────┐
           │  PostgreSQL 16 + pgvector          │
           │  + face_clusters table  ← NEW      │
           └────────────────────────────────────┘
                          ▲
           ┌──────────────┘
           │
┌────────────────────────┐
│  web (React 18 + Vite) │
│  nginx static serving  │
│  - Search, Videos,     │
│  - People, Clusters    │
│    (NEW page)          │
└────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | New in v1 clustering |
|-----------|---------------|----------------------|
| `ingestion-worker` | Frame extraction, YOLO, InsightFace, DB writes | No change |
| `api` | Search, enrollment, presigned URLs, cluster trigger, Telegram send | `POST /cluster/run`, `GET /digest/preview`, Telegram |
| `postgres` | All persistent state including cluster assignments | `face_clusters` table, `cluster_id` FK on `face_detections` |
| `web` | React UI including cluster browsing and labeling | Clusters page |
| `n8n` (external) | Ingestion trigger, daily cron for clustering + digest | New workflow #3: daily cron |

**Do NOT add a separate `batch-worker` container.** HDBSCAN on 512-dim vectors for tens of thousands of embeddings runs in < 5 seconds on CPU (pure Python/NumPy, no ML models). Adding a container for this creates operational complexity for a nightly job that takes seconds. Host it inside `api`.

---

## Processing Pipeline

### Per-Video Pipeline (sequential within a single worker process)

```
1. RECEIVE JOB
   n8n POSTs {minio_key} → ingestion-worker POST /ingest
   └─ Set videos.status = 'processing'

2. DOWNLOAD + EXTRACT FRAMES
   Download video from MinIO to /tmp/work/{video_id}/
   FFmpeg: 1 fps + scene-change frames
   Upload frames to MinIO: frames/{video_id}/{ts_ms}.jpg
   Write frames rows to Postgres
   └─ Sequential file I/O; no model loaded yet

3. YOLO OBJECT DETECTION  [model loaded once at startup, kept warm]
   Batch frames (8–16 at a time) through YOLOv8n
   Filter to configured COCO classes
   Write detections rows to Postgres
   └─ ~0.3 s/frame × 8 batch = ~2.4 s per batch; ~0.5 GB VRAM-equiv in RAM

4. INSIGHTFACE FACE ANALYSIS  [model loaded once at startup, kept warm]
   For each frame that has a 'person' detection OR every Nth frame:
     Run full-frame through SCRFD (face detector)
     For each detected face:
       Compute ArcFace 512-dim embedding (normed_embedding)
       Cosine search in pgvector against known_persons
       If similarity ≥ 0.5 → matched_person_id = <UUID>
       Else → matched_person_id = NULL (unknown)
       Write face_detections row
   └─ ~0.5–1.0 s/frame; 1.5 GB RAM

5. FINALIZE
   Set videos.status = 'done'
   Cleanup /tmp/work/{video_id}/
   Log summary (frames, detections, faces found)
```

**Critical ordering constraint:** Load BOTH models at process startup (not per-frame). 
Loading InsightFace buffalo_l takes ~3–5 seconds. Loading YOLO takes ~1 second. 
Always load once in the FastAPI lifespan event; never inside the frame loop.

```python
# ingestion-worker/app/main.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load at startup — kept in memory for the process lifetime
    app.state.yolo = YOLO("yolov8n.pt")
    app.state.face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.state.face_app.prepare(ctx_id=0, det_size=(640, 640))
    yield
    # Cleanup on shutdown (GC handles model release)
```

**Frame batching strategy for YOLO:**
```python
# Process in batches of 8-16 frames
YOLO_BATCH = 8
for i in range(0, len(frame_paths), YOLO_BATCH):
    batch = frame_paths[i:i+YOLO_BATCH]
    results = yolo_model(batch, imgsz=640, conf=0.35, classes=ALLOWED_CLASS_IDS)
```

InsightFace processes **one frame at a time** (it handles internal batching for multiple faces in a frame). Do not try to batch frames into InsightFace — it accepts a single BGR image array.

---

## Clustering Strategy

### Where Clustering Fits: Nightly Batch Job (NOT Per-Video)

**Do NOT cluster per-video.** A single video has too few unknown faces for HDBSCAN to find meaningful clusters (noise dominates small datasets). The signal emerges only when you cluster across the whole library.

```
Per-video pipeline completes
         │
         ▼ (async, no blocking)
unknown face_detections accumulate in DB
         │
         ▼ (nightly, triggered by n8n cron at 02:00)
POST /cluster/run
         │
         ▼
HDBSCAN on all face_detections WHERE matched_person_id IS NULL
         │
         ├─ Cluster 1 (Uncle Tom, 47 appearances across 12 videos)
         ├─ Cluster 2 (neighbor, 8 appearances)
         ├─ Noise (-1): one-off faces, false detections → stays unknown
         │
         ▼
Update face_detections.cluster_id
Upsert face_clusters (representative embedding, face count, thumbnail)
         │
         ▼
Telegram digest for known persons (separate from clustering result)
```

### Why HDBSCAN Over DBSCAN

| Criterion | DBSCAN | HDBSCAN | Winner |
|-----------|--------|---------|--------|
| Unknown cluster count | ✓ (no k needed) | ✓ (no k needed) | Tie |
| Varying density | ✗ (single eps) | ✓ (multi-scale) | HDBSCAN |
| Noise handling | ✓ | ✓ | Tie |
| Hyperparameter sensitivity | High (eps brittle) | Low (min_cluster_size robust) | HDBSCAN |
| Incremental clustering | ✗ | Partial (approximate_predict) | HDBSCAN |
| Performance at 10K-100K points | O(n²) naive | O(n log n) with boruvka_kdtree | HDBSCAN |
| Scikit-learn built-in | ✓ (since 0.15) | ✓ (since 1.3) | Tie |

**HDBSCAN wins decisively for this use case.** The key advantage is handling varying density: some people (family members who appear constantly) will have dense clusters; strangers who appear rarely will form sparse clusters. DBSCAN requires a single `eps` that works for all density levels — wrong for this workload.

### HDBSCAN Configuration for Face Embeddings

```python
from sklearn.cluster import HDBSCAN  # scikit-learn >= 1.3
import numpy as np
from sklearn.metrics import pairwise_distances

def cluster_unknown_faces(embeddings: np.ndarray) -> np.ndarray:
    """
    embeddings: shape (N, 512), L2-normalized ArcFace embeddings
    returns: cluster labels array, -1 = noise
    """
    if len(embeddings) < 3:
        return np.full(len(embeddings), -1)

    # Precompute cosine distance matrix
    # cosine distance = 1 - cosine_similarity (since embeddings are L2-normalized)
    dist_matrix = 1.0 - np.dot(embeddings, embeddings.T)
    dist_matrix = np.clip(dist_matrix, 0, None)  # numerical safety

    clusterer = HDBSCAN(
        min_cluster_size=3,      # at least 3 appearances = real person
        min_samples=2,            # noise sensitivity; lower = more points in clusters
        metric='precomputed',     # we supply distance matrix directly
        cluster_selection_epsilon=0.3,  # merge nearby clusters (cosine dist ≤ 0.3 = same person)
    )
    return clusterer.fit_predict(dist_matrix)
```

**Parameter guidance:**
- `min_cluster_size=3`: A person who appears in only 1–2 frames is classified as noise (-1). Tune up to 5 if you want to reduce false clusters.
- `cluster_selection_epsilon=0.3`: Equivalent to a similarity threshold of 0.7 — clusters closer than this are merged. Aligns with the 0.5 match threshold (clustering is less strict than identification).
- Use `metric='precomputed'` with a precomputed cosine distance matrix. Do NOT use `metric='cosine'` directly in HDBSCAN — it runs slower than precomputing with `np.dot`.

### Database Schema Additions for Clustering

```sql
-- Add to 001_schema.sql or create 002_clustering.sql

CREATE TABLE face_clusters (
    id              SERIAL PRIMARY KEY,
    label           INT NOT NULL,          -- HDBSCAN cluster label (0, 1, 2, ...)
    person_name     TEXT,                  -- NULL until user labels this cluster
    face_count      INT NOT NULL DEFAULT 0,
    representative_embedding vector(512),  -- centroid embedding for display
    thumbnail_minio_key TEXT,              -- best face crop for UI thumbnail
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_updated_at TIMESTAMPTZ DEFAULT now()
);

-- Add cluster FK to face_detections
ALTER TABLE face_detections 
    ADD COLUMN cluster_id INT REFERENCES face_clusters(id) ON DELETE SET NULL;

CREATE INDEX ON face_detections (cluster_id);
```

### Clustering Job Flow (inside `api` service)

```python
# api/app/routers/cluster.py

@router.post("/cluster/run")
async def run_clustering(db = Depends(get_db)):
    """
    Called by n8n daily cron at 02:00.
    Runs HDBSCAN on all unmatched face embeddings.
    """
    # 1. Fetch all unknown face embeddings with their IDs
    rows = await db.fetch("""
        SELECT id, embedding::float[]
        FROM face_detections
        WHERE matched_person_id IS NULL
        ORDER BY id
    """)
    
    if len(rows) < 3:
        return {"status": "skipped", "reason": "too few unknown faces"}
    
    ids = [r["id"] for r in rows]
    embeddings = np.array([r["embedding"] for r in rows], dtype=np.float32)
    
    # 2. Cluster
    labels = cluster_unknown_faces(embeddings)
    
    # 3. Upsert face_clusters and update face_detections
    # (truncate + rewrite on each run — simple and safe for small-scale)
    await db.execute("UPDATE face_detections SET cluster_id = NULL WHERE matched_person_id IS NULL")
    await db.execute("DELETE FROM face_clusters")
    
    unique_labels = set(labels) - {-1}
    for label in unique_labels:
        mask = labels == label
        cluster_embeddings = embeddings[mask]
        centroid = cluster_embeddings.mean(axis=0)
        centroid /= np.linalg.norm(centroid)
        
        cluster_id = await db.fetchval("""
            INSERT INTO face_clusters (label, face_count, representative_embedding)
            VALUES ($1, $2, $3::vector)
            RETURNING id
        """, int(label), int(mask.sum()), centroid.tolist())
        
        cluster_face_ids = [ids[i] for i, m in enumerate(mask) if m]
        await db.execute("""
            UPDATE face_detections SET cluster_id = $1
            WHERE id = ANY($2::bigint[])
        """, cluster_id, cluster_face_ids)
    
    return {"status": "ok", "clusters": len(unique_labels), "noise": int((labels == -1).sum())}
```

### On-Demand Re-Clustering

Expose `POST /cluster/run?force=true` so the user can trigger re-clustering after labeling a cluster as a known person (which moves those faces to `matched_person_id`, removing them from the unknown pool before next cluster run).

---

## Notification Architecture

### Telegram Daily Digest

**Architecture decision:** The API service sends Telegram directly — do NOT route through n8n for message construction. n8n cron calls `POST /cluster/run` then `POST /digest/send`. Keeping message logic in Python gives you full control over formatting and thumbnail attachment.

```
n8n daily cron (02:00)
    │
    ├─ POST http://api:8000/cluster/run      ← clustering
    │        wait for 200 OK
    │
    └─ POST http://api:8000/digest/send      ← Telegram notification
             builds message from DB query
             sends via python-telegram-bot
```

**Dependencies:**
```txt
# requirements.txt addition for api service
python-telegram-bot==22.*    # v22 is current as of research date
```

**Implementation pattern:**
```python
# api/app/services/telegram.py
import telegram

async def send_daily_digest(
    bot_token: str,
    chat_id: str | int,
    db,
    since_hours: int = 24
):
    """Send family appearance summary for the last N hours."""
    bot = telegram.Bot(token=bot_token)
    
    # Query DB for recent known person appearances
    rows = await db.fetch("""
        SELECT kp.name, COUNT(DISTINCT fd.frame_id) AS appearances,
               MIN(v.recorded_at) AS earliest_video
        FROM face_detections fd
        JOIN known_persons kp ON kp.id = fd.matched_person_id
        JOIN frames f ON f.id = fd.frame_id
        JOIN videos v ON v.id = f.video_id
        WHERE fd.matched_person_id IS NOT NULL
          AND v.ingested_at >= now() - ($1 || ' hours')::interval
        GROUP BY kp.name
        ORDER BY appearances DESC
    """, since_hours)
    
    if not rows:
        text = "📹 No new family appearances in the last 24 hours."
    else:
        lines = ["📹 *Daily Video Summary*\n"]
        for row in rows:
            lines.append(f"👤 *{row['name']}*: {row['appearances']} appearances")
        text = "\n".join(lines)
    
    async with bot:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=telegram.constants.ParseMode.MARKDOWN_V2
        )
```

**Environment variables to add:**
```env
TELEGRAM_BOT_TOKEN=<bot token from @BotFather>
TELEGRAM_CHAT_ID=<your personal chat ID>
TELEGRAM_DIGEST_ENABLED=true
```

**Confidence:** HIGH — `python-telegram-bot` v22 confirmed via Context7, `bot.send_message()` API stable.

---

## Memory Management

### Memory Budget on i5-6200 / 8 GB RAM

| Component | RSS at steady state | Notes |
|-----------|--------------------|----|
| OS + system daemons | ~800 MB | Ubuntu minimal |
| Docker overhead | ~200 MB | Shared kernel |
| PostgreSQL 16 | ~800 MB – 1.2 GB | `shared_buffers=256MB` default; `effective_cache_size=1GB` |
| `ingestion-worker` baseline | ~300 MB | FastAPI + asyncpg before models |
| YOLOv8n model (loaded) | ~500 MB | `.pt` weights + ONNX runtime |
| InsightFace buffalo_l (loaded) | ~1.4 GB | SCRFD-10GF + ArcFace ONNX |
| `api` service | ~200 MB | FastAPI + asyncpg + scikit-learn |
| `web` (nginx) | ~50 MB | Negligible |
| **Total peak (during ingestion)** | **~5.25 GB** | **2.75 GB headroom** |

### Risk Areas

**Risk 1: Simultaneous model loading at startup (HIGH risk)**  
If `ingestion-worker` is restarted during active ingestion, YOLO and InsightFace load simultaneously. Combined peak during loading can briefly spike to ~3 GB for the worker alone.
- **Mitigation:** Add 2-second sleep between YOLO load and InsightFace load in lifespan startup. Load YOLO first (smaller), then InsightFace.

**Risk 2: Postgres not releasing memory after large queries**  
PostgreSQL `work_mem` (default 4 MB) can multiply by parallel workers. The pgvector HNSW index construction uses significant RAM.
- **Mitigation:** Set `max_parallel_workers_per_gather=0` in postgres config during ingestion to prevent parallel query plans. Use `work_mem=8MB` (conservative).

**Risk 3: HDBSCAN on large embedding sets**  
Precomputed cosine distance matrix for N faces = N² floats. At 50,000 unknown faces: 50,000² × 4 bytes = **10 GB** — exceeds available RAM.
- **Mitigation:** Do not run HDBSCAN on the full dataset naively. Use a two-stage approach:
  1. Pre-filter with pgvector ANN to find face groups (neighborhoods)
  2. Run HDBSCAN on batches of ≤ 10,000 embeddings, merge clusters afterward
  - OR: use `algorithm='boruvka_kdtree'` (does NOT require precomputed matrix, uses O(n log n) memory) with `metric='euclidean'` on normalized vectors (equivalent to cosine distance on L2-normalized vectors since `||a-b||² = 2 - 2·cos(θ)`)
  - For a home video library with < 10,000 hours: realistic max ~100,000 unknown faces. Use boruvka_kdtree for safety.

```python
# Safe HDBSCAN for large N — no O(n²) memory
clusterer = HDBSCAN(
    min_cluster_size=3,
    min_samples=2,
    metric='euclidean',          # works on L2-normalized vectors (= cosine)
    algorithm='boruvka_kdtree',  # O(n log n) memory, fast
    cluster_selection_epsilon=0.55,  # sqrt(2*(1-0.7)) ≈ 0.775, adjust empirically
)
labels = clusterer.fit_predict(embeddings)  # embeddings already L2-normalized
```

**Risk 4: Frame temp directory fill (MEDIUM risk)**  
1 fps on a 2-hour video = 7,200 frames × ~150 KB JPEG = ~1 GB temp disk per video.
- **Mitigation:** Upload frames to MinIO and delete temp files as you go (streaming upload, not batch). Cap `WORK_DIR_MAX_GB=2` via config.

### Docker Compose Memory Limits

```yaml
services:
  ingestion-worker:
    deploy:
      resources:
        limits:
          memory: 5g           # Already in requirements.md — correct
        reservations:
          memory: 2g           # Ensure it always gets 2 GB
  api:
    deploy:
      resources:
        limits:
          memory: 1g           # Enough for FastAPI + HDBSCAN + python-telegram-bot
  postgres:
    deploy:
      resources:
        limits:
          memory: 1500m        # With 256MB shared_buffers
```

### OMP Thread Configuration (Critical)

```yaml
# ingestion-worker environment:
OMP_NUM_THREADS: "4"          # ONNX Runtime threads (half of i5-6200's 4 logical cores)
OPENBLAS_NUM_THREADS: "4"     # NumPy/SciPy (used by HDBSCAN)
MKL_NUM_THREADS: "4"
```

Do NOT use all 4 cores for OMP — leave 0–1 cores for I/O, MinIO client, and Postgres asyncpg connections.

### Swap File

Add a 4 GB swap file on the Ubuntu host as a safety net (already recommended in requirements.md):
```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```
Swap prevents OOM kills at the cost of degraded performance. Acceptable since ingestion is a background task.

---

## Video Streaming Architecture

### Decision: Presigned URLs via API Redirect (NOT Proxy)

```
Browser                  API                    MinIO
   │                      │                        │
   ├─GET /videos/{id}/stream──►                    │
   │                      │ presigned_url =         │
   │                      │ minio.presigned_get(    │
   │                      │   key, expires=3600)    │
   │   302 Location: <presigned_url>                │
   ◄─────────────────────-┤                        │
   │                      │                        │
   ├─GET <presigned_url> (follows redirect)────────►│
   │                      │        stream bytes     │
   ◄───────────────────────────────────────────────┤
```

**Why presigned URLs, not proxy:**
- Zero bandwidth overhead on API (video can be gigabytes)
- MinIO supports HTTP Range requests natively — `<video>` element seeks work correctly
- API service stays memory-efficient (no buffering)
- Presigned URLs expire (1 hour default) — no persistent credential exposure

**MinIO CORS configuration required** (needed for browser direct access):
```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": ["https://search.shumov.eu"],
    "ExposeHeaders": ["Content-Length", "Accept-Ranges", "Content-Range"]
  }
]
```
Apply via: `mc cors set --json cors.json myminio/videos`

**Frame thumbnail presigned URLs** work identically: `GET /frames/{id}/image` → 302 to `frames/{video_id}/{ts_ms}.jpg` presigned URL.

**Presigned URL generation (Python):**
```python
from minio import Minio
from datetime import timedelta

minio_client = Minio(...)

def presigned_video_url(minio_key: str) -> str:
    return minio_client.presigned_get_object(
        bucket_name="videos",
        object_name=minio_key,
        expires=timedelta(hours=1)
    )
```

**Confidence:** HIGH — MinIO presigned GET confirmed via Context7 docs; CORS requirement verified from MinIO documentation.

---

## Build Order

### Phase Dependencies

```
Phase 1: Infrastructure Foundation
├── Docker Compose scaffold (postgres only)
├── DB schema + pgvector extension
├── MinIO client wrapper
└── Verify: psql + minio ping from both services

Phase 2: Core Ingestion Pipeline   ← depends on Phase 1
├── ingestion-worker skeleton (FastAPI + /health + /ingest)
├── FFmpeg frame extraction module
├── Frame upload to MinIO + frames table writes
└── Verify: ingest a 10s test video, see frames in MinIO + DB

Phase 3: ML Detection   ← depends on Phase 2
├── YOLO integration (load at startup, batch frames)
├── detections table writes
├── InsightFace integration (full frame, NOT YOLO crop)
├── face_detections table writes (no matching yet, all unknown)
└── Verify: test video, assert detection counts

Phase 4: Face Enrollment + Matching   ← depends on Phase 3
├── known_persons + person_embeddings tables
├── pgvector HNSW index
├── Enrollment endpoint (POST /persons/{id}/enroll)
├── Cosine similarity matching in ingestion pipeline
└── Verify: enroll a face, re-ingest video, assert matched_person_id populated

Phase 5: Search API   ← depends on Phase 3 (can run before Phase 4)
├── GET /videos, GET /videos/{id}
├── POST /search (all filter combinations)
├── GET /videos/{id}/stream → presigned URL
├── GET /frames/{id}/image → presigned URL
└── Verify: search returns correct frames; video plays in browser at ts_ms

Phase 6: Web UI   ← depends on Phase 5
├── Settings page (API token, base URL)
├── People page (enroll, list, appearances)
├── Search page (filters, result grid, modal + video play)
├── Videos page (status, re-ingest)
└── Verify: full round-trip via UI

Phase 7: n8n Integration   ← depends on Phase 5
├── Workflow 1: MinIO event → POST /ingest
├── Workflow 2: (optional) scheduled scan every 10 min
└── Verify: drop a video in MinIO, watch it auto-ingest

Phase 8: Unknown Face Clustering   ← depends on Phase 4
├── face_clusters table migration
├── cluster_id FK on face_detections
├── HDBSCAN clustering job (POST /cluster/run in api)
├── Cluster browsing UI (new page: Clusters)
├── Cluster labeling → converts cluster to known_person
└── Verify: ingest 5+ videos, run clustering, see grouped faces in UI

Phase 9: Telegram Digest   ← depends on Phase 8, Phase 7
├── python-telegram-bot dependency in api
├── POST /digest/send endpoint
├── n8n Workflow 3: daily cron 02:00 → /cluster/run → /digest/send
└── Verify: trigger manually, receive Telegram message

Phase 10: Import Flow   ← can be done in parallel with Phase 7+
├── POST /ingest/batch endpoint (scan MinIO prefix)
├── Bulk import script for NAS → MinIO
└── Verify: 100+ videos ingested without duplicate rows

Phase 11: Hardening   ← depends on all above
├── Auth middleware (Bearer token, skip /health /docs in dev)
├── Retry logic for failed ingestion (re-queue on startup)
├── Error message column on videos table
├── Swap file setup, Docker memory limits
├── Basic metrics endpoint (/metrics, Prometheus format)
└── Verify: restart during ingestion, video re-queued automatically
```

### Critical Dependency Notes

1. **Phase 3 before Phase 4**: You cannot do matching until embeddings exist. Run Phase 3 on test data first, then add matching in Phase 4.

2. **Phase 8 is standalone feature territory**: Do not block v1 launch on clustering. The core product (search by known person + object class) is complete after Phase 6. Phases 8–9 are the "clustering milestone" that comes after first working version.

3. **Phase 10 (import flow) is a prerequisite for real-world use** but not for development testing. Prioritize after Phase 7.

4. **ingestion-worker and api share no code** intentionally. Both have their own DB pool, both are separate Docker services. Do NOT make api call ingestion-worker internally — n8n is the orchestrator.

5. **The `cluster_id` column** can be added to `face_detections` via a migration in Phase 8 without breaking Phase 1–7 behavior (it's nullable, existing rows get NULL).

---

## Sources

| Claim | Source | Confidence |
|-------|--------|------------|
| HDBSCAN handles varying density better than DBSCAN | Context7: scikit-learn-contrib/hdbscan docs | HIGH |
| HDBSCAN precomputed cosine distance matrix | Context7: scikit-learn-contrib/hdbscan, pairwise_distances example | HIGH |
| HDBSCAN in scikit-learn since 1.3 | scikit-learn docs via Context7 | HIGH |
| MinIO presigned GET URL via Python SDK | Context7: minio/docs | HIGH |
| MinIO CORS required for browser direct access | MinIO docs (standard S3 pattern) | HIGH |
| python-telegram-bot v22, bot.send_message() | Context7: python-telegram-bot/python-telegram-bot | HIGH |
| InsightFace buffalo_l CPU memory ~1.4 GB | requirements.md baseline + InsightFace ONNX model size | MEDIUM |
| YOLOv8n CPU memory ~0.5 GB | requirements.md baseline + Ultralytics docs | MEDIUM |
| HDBSCAN boruvka_kdtree O(n log n) memory | Context7: scikit-learn-contrib/hdbscan performance docs | HIGH |
| Precomputed distance matrix O(n²) memory warning | Mathematical analysis (N² floats) | HIGH |
