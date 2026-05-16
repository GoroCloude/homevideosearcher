---
plan: "01 — Docker Compose + Schema"
phase: 1
wave: 1
depends_on: []
files_modified:
  - docker-compose.yml
  - .env.example
  - db/init/001_schema.sql
  - services/ingestion-worker/Dockerfile
  - services/ingestion-worker/requirements.txt
  - services/api/Dockerfile
  - services/api/requirements.txt
  - services/api/app/main.py
  - services/web/Dockerfile
  - docs/operations.md
autonomous: true
requirements:
  - INFRA-01
  - INFRA-02
  - INFRA-03
  - INFRA-04
  - INFRA-05
  - INFRA-06
  - INFRA-07
  - INFRA-08

must_haves:
  truths:
    - "`docker compose up` starts all four services (postgres, ingestion-worker, api, web) without errors"
    - "PostgreSQL schema contains `face_detections.unknown_cluster_id`, `face_detections.match_tier`, and `unknown_clusters` table from day 1"
    - "HNSW indexes on `person_embeddings.normed_embedding` and `face_detections.normed_embedding` use m=32, ef_construction=128"
    - "hnsw.ef_search=64 is set on the postgres service"
    - "Two-tier threshold env vars `FACE_MATCH_HIGH_THRESHOLD=0.65` and `FACE_MATCH_LOW_THRESHOLD=0.50` are defined"
    - "InsightFace buffalo_l model is baked into the ingestion-worker Docker image at build time (not downloaded at startup)"
    - "`GET /health` returns 200 on both ingestion-worker (:8001) and api (:8000)"
    - ".env.example covers all required env vars; docs/operations.md documents 4 GB swap file"
  artifacts:
    - path: "docker-compose.yml"
      provides: "Four-service Compose stack with external home-infra network"
      contains: "services: postgres, ingestion-worker, api, web"
    - path: "db/init/001_schema.sql"
      provides: "Full PostgreSQL schema"
      contains: "unknown_clusters, face_detections, match_tier, unknown_cluster_id, hnsw"
    - path: "services/ingestion-worker/Dockerfile"
      provides: "Ingestion-worker image with baked ML models"
      contains: "buffalo_l"
    - path: ".env.example"
      provides: "All required env vars with safe defaults"
      contains: "FACE_MATCH_HIGH_THRESHOLD"
    - path: "docs/operations.md"
      provides: "Ops guide"
      contains: "swap"
  key_links:
    - from: "docker-compose.yml postgres service"
      to: "db/init/001_schema.sql"
      via: "./db/init:/docker-entrypoint-initdb.d:ro volume mount"
      pattern: "docker-entrypoint-initdb.d"
    - from: "docker-compose.yml ingestion-worker"
      to: "home-infra external network"
      via: "networks declaration"
      pattern: "external: true"
    - from: "face_detections.unknown_cluster_id"
      to: "unknown_clusters.id"
      via: "UUID FK with ON DELETE SET NULL"
      pattern: "REFERENCES unknown_clusters"
---

# Plan 01: Docker Compose + Schema

## Goal

Provision the complete infrastructure shell: Docker Compose stack with all four services, the full PostgreSQL schema (all columns present from day 1 — no future migrations for clustering or thresholds), Dockerfiles with baked ML models, environment config, and the ops guide.

---

## Tasks

<task id="01.1">
<title>Create docker-compose.yml and .env.example</title>
<read_first>
- requirements.md §4 (architecture diagram), §7 (configuration env vars), §8 (Docker Compose layout)
- .planning/STATE.md (external services: MinIO and n8n on home-infra network; memory constraints)
- .planning/research/SUMMARY.md §3 (Docker Day 1 Checklist — external network, depends_on service_healthy, memory limits)
</read_first>
<action>
Create `docker-compose.yml` at the repo root. Use exact values below — do not deviate from names or params:

```yaml
services:
  postgres:
    image: pgvector/pgvector:0.8.2-pg16
    command: ["postgres", "-c", "hnsw.ef_search=64"]
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-videosearch}
      POSTGRES_USER: ${POSTGRES_USER:-videosearch}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-videosearch} -d ${POSTGRES_DB:-videosearch}"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks:
      - home-infra

  ingestion-worker:
    build: ./services/ingestion-worker
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-videosearch}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-videosearch}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET_VIDEOS: ${MINIO_BUCKET_VIDEOS:-videos}
      MINIO_BUCKET_FRAMES: ${MINIO_BUCKET_FRAMES:-frames}
      MINIO_USE_SSL: ${MINIO_USE_SSL:-false}
      YOLO_MODEL: ${YOLO_MODEL:-yolov8n.pt}
      YOLO_CONFIDENCE: ${YOLO_CONFIDENCE:-0.35}
      YOLO_CLASSES: ${YOLO_CLASSES:-person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird}
      YOLO_BATCH_SIZE: ${YOLO_BATCH_SIZE:-8}
      FACE_MATCH_HIGH_THRESHOLD: ${FACE_MATCH_HIGH_THRESHOLD:-0.65}
      FACE_MATCH_LOW_THRESHOLD: ${FACE_MATCH_LOW_THRESHOLD:-0.50}
      OMP_NUM_THREADS: ${OMP_NUM_THREADS:-4}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 5g
    networks:
      - home-infra

  api:
    build: ./services/api
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-videosearch}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-videosearch}
      MINIO_ENDPOINT: ${MINIO_ENDPOINT:-minio:9000}
      MINIO_ACCESS_KEY: ${MINIO_ACCESS_KEY}
      MINIO_SECRET_KEY: ${MINIO_SECRET_KEY}
      MINIO_BUCKET_VIDEOS: ${MINIO_BUCKET_VIDEOS:-videos}
      MINIO_BUCKET_FRAMES: ${MINIO_BUCKET_FRAMES:-frames}
      MINIO_USE_SSL: ${MINIO_USE_SSL:-false}
      API_TOKEN: ${API_TOKEN}
      API_CORS_ORIGINS: ${API_CORS_ORIGINS:-http://localhost:8080}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
    ports:
      - "${API_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - home-infra

  web:
    build: ./services/web
    ports:
      - "${WEB_PORT:-8080}:80"
    networks:
      - home-infra

networks:
  home-infra:
    external: true

volumes:
  pgdata:
```

Create `.env.example` at the repo root with every variable the stack consumes:

```
# ── PostgreSQL ──────────────────────────────────────────────────────────────
POSTGRES_DB=videosearch
POSTGRES_USER=videosearch
POSTGRES_PASSWORD=change-me-in-production

# ── MinIO (external — already running on home-infra network) ────────────────
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=your-minio-access-key
MINIO_SECRET_KEY=your-minio-secret-key
MINIO_BUCKET_VIDEOS=videos
MINIO_BUCKET_FRAMES=frames
MINIO_USE_SSL=false

# ── YOLO Object Detection ────────────────────────────────────────────────────
YOLO_MODEL=yolov8n.pt
YOLO_CONFIDENCE=0.35
YOLO_CLASSES=person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird
YOLO_BATCH_SIZE=8

# ── Face Recognition (two-tier thresholds — do not lower without testing) ───
FACE_MATCH_HIGH_THRESHOLD=0.65
FACE_MATCH_LOW_THRESHOLD=0.50

# ── API ──────────────────────────────────────────────────────────────────────
API_TOKEN=replace-with-long-random-secret
API_CORS_ORIGINS=https://search.shumov.eu
API_PORT=8000
WEB_PORT=8080

# ── Runtime ──────────────────────────────────────────────────────────────────
OMP_NUM_THREADS=4
LOG_LEVEL=INFO
```
</action>
<acceptance_criteria>
- `docker-compose.yml` contains exactly: `services: postgres, ingestion-worker, api, web`
- `docker-compose.yml` contains `networks: home-infra: external: true`
- `docker-compose.yml` postgres service has `command: ["postgres", "-c", "hnsw.ef_search=64"]`
- `docker-compose.yml` postgres healthcheck uses `pg_isready`
- `docker-compose.yml` ingestion-worker and api both have `depends_on: postgres: condition: service_healthy`
- `docker-compose.yml` ingestion-worker has `deploy.resources.limits.memory: 5g`
- `.env.example` contains `FACE_MATCH_HIGH_THRESHOLD=0.65` and `FACE_MATCH_LOW_THRESHOLD=0.50`
- `.env.example` contains `YOLO_CLASSES=person,bicycle,car,...` (12 default classes)
- Verify: `grep -c "service_healthy" docker-compose.yml` returns `2`
- Verify: `grep "external: true" docker-compose.yml` returns a match
</acceptance_criteria>
</task>

<task id="01.2">
<title>Create db/init/001_schema.sql — full PostgreSQL schema</title>
<read_first>
- requirements.md §5 (Data Model — base schema)
- .planning/STATE.md (Architecture constraints: unknown_cluster_id, match_tier, unknown_clusters table, HNSW m=32/ef_construction=128, error_message column)
- .planning/research/PITFALLS.md §FR-4 (normed_embedding — must be named normed_embedding not embedding to force correct field access)
- .planning/research/SUMMARY.md §Critical Design Decisions §1 (two-tier threshold schema)
</read_first>
<action>
Create `db/init/001_schema.sql`. This script runs once on first `docker compose up`. Every column needed by Phase 1–3 clustering must be present now.

```sql
-- HomeVideoSearcher — PostgreSQL 16 + pgvector 0.8.2
-- IMPORTANT: Run on a fresh database only. After first deploy, use Alembic migrations.
-- HNSW params: m=32, ef_construction=128 applied to all vector indexes.
-- hnsw.ef_search=64 is set at the postgres service level (docker-compose command arg).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid() fallback

-- ── Videos ──────────────────────────────────────────────────────────────────
CREATE TABLE videos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minio_key       TEXT NOT NULL UNIQUE,
    filename        TEXT NOT NULL,
    duration_sec    NUMERIC,
    width           INT,
    height          INT,
    fps             NUMERIC,
    recorded_at     TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    error_message   TEXT          -- populated on status='failed'
);
CREATE INDEX ON videos (status);
CREATE INDEX ON videos (ingested_at DESC);

-- ── Frames ──────────────────────────────────────────────────────────────────
-- Only frames with at least one detection (YOLO or face) are stored.
CREATE TABLE frames (
    id              BIGSERIAL PRIMARY KEY,
    video_id        UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    ts_ms           INT NOT NULL,                   -- ms from start of video
    minio_key       TEXT NOT NULL,                  -- "frames/{video_id}/{ts_ms}.jpg"
    UNIQUE (video_id, ts_ms)
);
CREATE INDEX ON frames (video_id, ts_ms);

-- ── Detections (YOLO output) ─────────────────────────────────────────────────
CREATE TABLE detections (
    id              BIGSERIAL PRIMARY KEY,
    frame_id        BIGINT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    class_name      TEXT NOT NULL,
    confidence      REAL NOT NULL,
    bbox_x1         INT,
    bbox_y1         INT,
    bbox_x2         INT,
    bbox_y2         INT
);
CREATE INDEX ON detections (frame_id);
CREATE INDEX ON detections (class_name);

-- ── Known persons (enrollment) ───────────────────────────────────────────────
CREATE TABLE known_persons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per enrollment image. Multiple embeddings per person for robustness.
-- Column is named normed_embedding (not embedding) to enforce correct field access.
CREATE TABLE person_embeddings (
    id                  BIGSERIAL PRIMARY KEY,
    person_id           UUID NOT NULL REFERENCES known_persons(id) ON DELETE CASCADE,
    normed_embedding    vector(512) NOT NULL,        -- InsightFace face.normed_embedding
    source_image        TEXT,                        -- MinIO key of source enrollment photo
    created_at          TIMESTAMPTZ DEFAULT now()
);
-- HNSW index: m=32, ef_construction=128 (not pgvector defaults m=16)
CREATE INDEX person_embeddings_hnsw_idx
    ON person_embeddings
    USING hnsw (normed_embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 128);

-- ── Unknown face clusters (stable UUIDs — Phase 3 populates this) ────────────
-- Created here so face_detections.unknown_cluster_id FK is valid from day 1.
-- Populated by POST /cluster/run (Phase 3). Never truncated and rewritten
-- — cluster UUIDs are stable across nightly runs.
CREATE TABLE unknown_clusters (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    representative_face_id  BIGINT,             -- FK set after face_detections created
    appearance_count        INT NOT NULL DEFAULT 0,
    first_seen              TIMESTAMPTZ,
    last_seen               TIMESTAMPTZ,
    created_at              TIMESTAMPTZ DEFAULT now()
);

-- ── Face detections (InsightFace output) ─────────────────────────────────────
-- match_tier: 'confident' (>=0.65), 'probable' (0.50-0.65), NULL (unknown/unmatched)
-- unknown_cluster_id: set by Phase 3 clustering job; NULL until then
CREATE TABLE face_detections (
    id                  BIGSERIAL PRIMARY KEY,
    frame_id            BIGINT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    bbox_x1             INT,
    bbox_y1             INT,
    bbox_x2             INT,
    bbox_y2             INT,
    det_score           REAL,                   -- SCRFD face detector confidence
    normed_embedding    vector(512) NOT NULL,   -- ArcFace normed_embedding (L2-normalized)
    matched_person_id   UUID REFERENCES known_persons(id) ON DELETE SET NULL,
    match_similarity    REAL,                   -- cosine similarity to best match
    match_tier          TEXT CHECK (match_tier IN ('confident', 'probable')),
    unknown_cluster_id  UUID REFERENCES unknown_clusters(id) ON DELETE SET NULL
);
-- HNSW index: m=32, ef_construction=128
CREATE INDEX face_detections_hnsw_idx
    ON face_detections
    USING hnsw (normed_embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 128);
CREATE INDEX ON face_detections (frame_id);
CREATE INDEX ON face_detections (matched_person_id);
CREATE INDEX ON face_detections (unknown_cluster_id);
CREATE INDEX ON face_detections (match_tier);

-- Back-reference: unknown_clusters -> its representative face
ALTER TABLE unknown_clusters
    ADD CONSTRAINT fk_representative_face
    FOREIGN KEY (representative_face_id)
    REFERENCES face_detections(id)
    ON DELETE SET NULL;
```
</action>
<acceptance_criteria>
- File `db/init/001_schema.sql` exists
- `grep "unknown_cluster_id" db/init/001_schema.sql` returns a match in `face_detections`
- `grep "match_tier" db/init/001_schema.sql` returns `CHECK (match_tier IN ('confident', 'probable'))`
- `grep "unknown_clusters" db/init/001_schema.sql` returns `CREATE TABLE unknown_clusters`
- `grep "m = 32, ef_construction = 128" db/init/001_schema.sql` returns 2 matches (one for each HNSW index)
- `grep "normed_embedding" db/init/001_schema.sql` returns matches for both `person_embeddings` and `face_detections` tables
- `grep "error_message" db/init/001_schema.sql` returns a match in `videos` table
- `grep "status IN" db/init/001_schema.sql` returns `'pending', 'processing', 'done', 'failed'`
- Schema creates tables in dependency order (no FK forward-reference errors)
</acceptance_criteria>
</task>

<task id="01.3">
<title>Create Dockerfiles for all three services, requirements.txt files, and docs/operations.md</title>
<read_first>
- .planning/research/STACK.md §2 (InsightFace buffalo_l baking instructions), §1 (YOLO model download)
- .planning/research/SUMMARY.md §Docker Day 1 Checklist (bake models at build time)
- .planning/STATE.md (uv==0.11.14 as package manager; Python 3.11 required for insightface)
- requirements.md §10 (performance: OMP_NUM_THREADS=4 for i5-6200)
</read_first>
<action>
Create `services/ingestion-worker/requirements.txt`:
```
fastapi==0.136.1
uvicorn[standard]==0.35.0
asyncpg==0.31.0
pgvector==0.4.2
minio==7.2.20
ultralytics==8.4.51
insightface==0.7.3
onnxruntime==1.26.0
opencv-python-headless>=4.10
numpy<2.0
pydantic>=2.0
python-multipart>=0.0.20
```

Create `services/ingestion-worker/Dockerfile`:
```dockerfile
FROM python:3.11-slim-bookworm

# System dependencies: FFmpeg for frame extraction, libGL for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager (faster than pip; pinned version)
RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /app

# Install Python dependencies via uv
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code
COPY app/ ./app/

# ── Bake ML models at build time ──────────────────────────────────────────────
# YOLO model (~6 MB weights for yolov8n.pt) → ~/.cache/ultralytics/
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt'); print('YOLO baked')"

# InsightFace buffalo_l (~280 MB: SCRFD-10G + ArcFace R100) → ~/.insightface/models/
RUN python -c "
from insightface.app import FaceAnalysis
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))
print('InsightFace buffalo_l baked successfully')
"
# ─────────────────────────────────────────────────────────────────────────────

# ONNX Runtime thread count for i5-6200 (dual-core, 4 HT threads)
ENV OMP_NUM_THREADS=4
ENV PYTHONUNBUFFERED=1

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

Create `services/api/requirements.txt`:
```
fastapi==0.136.1
uvicorn[standard]==0.35.0
asyncpg==0.31.0
pgvector==0.4.2
minio==7.2.20
python-multipart>=0.0.20
pydantic>=2.0
scikit-learn==1.8.0
python-telegram-bot==22.*
```

Create `services/api/Dockerfile`:
```dockerfile
FROM python:3.11-slim-bookworm

RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /app

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `services/api/app/` directory and `services/api/app/main.py` — a minimal FastAPI app with just /health for Phase 1 (full routes added in Phase 2):
```python
"""
HomeVideoSearcher API service.
Phase 1: /health only. Full routes added in Phase 2 (Enrollment, Search).
"""
import logging
import os
from fastapi import FastAPI

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="HomeVideoSearcher API", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api"}
```

Create `services/web/Dockerfile` — a placeholder nginx static server that will be replaced by the full React build in Phase 4:
```dockerfile
FROM nginx:1.27-alpine

# Minimal placeholder until Phase 4 React build
RUN echo '<html><body><h1>HomeVideoSearcher</h1><p>UI coming in Phase 4.</p></body></html>' \
    > /usr/share/nginx/html/index.html

EXPOSE 80
```

Create `docs/operations.md` — the ops guide required by INFRA-08:
```markdown
# HomeVideoSearcher — Operations Guide

## Server Requirements

- **OS:** Ubuntu 22.04 LTS or 24.04 LTS
- **CPU:** Dual-core x86_64 (tested on i5-6200, 2 physical cores, 4 threads)
- **RAM:** 8 GB minimum
- **Disk:** 50 GB+ for video archive; SSD recommended

## ⚠️ Required: 4 GB Swap File

The ingestion-worker loads two ML models simultaneously:
- YOLOv8n: ~0.5 GB RSS
- InsightFace buffalo_l: ~1.5 GB RSS
- Postgres + OS buffers: ~2 GB

On an 8 GB host, peak usage during frame processing can reach 7.5–8 GB.
**Without swap, the Linux OOM killer will terminate the ingestion-worker.**

Create the swap file before starting the stack:

```bash
# Run as root on the Ubuntu host
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Verify:
```bash
free -h  # should show ~4G swap available
```

## External Docker Network

MinIO and n8n run on the `home-infra` Docker network. Create it once before
running the stack for the first time:

```bash
docker network create home-infra
```

If the network already exists (because MinIO/n8n created it), this command
returns an error — that is fine.

## First-Time Setup

1. Create swap file (see above)
2. Ensure `home-infra` Docker network exists
3. Copy `.env.example` to `.env` and fill in secrets:
   ```bash
   cp .env.example .env
   nano .env   # set POSTGRES_PASSWORD, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, API_TOKEN
   ```
4. Start the stack:
   ```bash
   docker compose up -d
   ```
5. Verify health:
   ```bash
   curl http://localhost:8001/health  # ingestion-worker
   curl http://localhost:8000/health  # api
   ```

## First Build Time

The `ingestion-worker` Docker image bakes the InsightFace buffalo_l model
(~280 MB) at build time. First `docker compose build` may take 10–15 minutes
depending on internet speed.

## Model Locations (inside the container)

| Model | Path inside container |
|-------|-----------------------|
| YOLOv8n | `/root/.cache/ultralytics/assets/yolov8n.pt` |
| InsightFace buffalo_l | `/root/.insightface/models/buffalo_l/` |

Both models are baked into the Docker image layer. Container startup is fast.

## Memory Limits

The ingestion-worker is limited to 5 GB RAM via `deploy.resources.limits.memory`.
If the container is OOM-killed, check that the 4 GB swap file is active.

## Useful Commands

```bash
# View ingestion-worker logs
docker compose logs -f ingestion-worker

# Check HNSW index parameters in Postgres
docker compose exec postgres psql -U videosearch videosearch \
  -c "SELECT indexname, reloptions FROM pg_indexes JOIN pg_class ON indexname = relname WHERE indexname LIKE '%hnsw%';"

# Trigger manual ingest
curl -X POST http://localhost:8001/ingest \
  -H "Content-Type: application/json" \
  -d '{"minio_key": "videos/your-clip.mp4"}'
```
```
</action>
<acceptance_criteria>
- `services/ingestion-worker/Dockerfile` exists and contains `insightface==0.7.3` reference and model baking RUN instructions
- `grep "buffalo_l" services/ingestion-worker/Dockerfile` returns a match
- `grep "uv pip install" services/ingestion-worker/Dockerfile` returns a match (uv, not pip install directly)
- `grep "libgl1" services/ingestion-worker/Dockerfile` returns a match (OpenCV system dep)
- `grep "OMP_NUM_THREADS" services/ingestion-worker/Dockerfile` returns `ENV OMP_NUM_THREADS=4`
- `services/api/app/main.py` exists with `/health` endpoint returning `{"status": "ok"}`
- `grep "fallocate" docs/operations.md` returns a match (swap file documentation)
- `grep "home-infra" docs/operations.md` returns a match
- `services/ingestion-worker/requirements.txt` contains `insightface==0.7.3` and `onnxruntime==1.26.0`
- `services/api/requirements.txt` contains `scikit-learn==1.8.0`
- `services/web/Dockerfile` exists with nginx base image
</acceptance_criteria>
</task>

---

## Verification

- [ ] `docker network create home-infra` (or verify it exists already) — must succeed before compose up
- [ ] Copy `.env.example` to `.env`, set `POSTGRES_PASSWORD=test`, `MINIO_ACCESS_KEY=test`, `MINIO_SECRET_KEY=test`, `API_TOKEN=test`
- [ ] `docker compose build` completes without error; ingestion-worker build shows "InsightFace buffalo_l baked successfully"
- [ ] `docker compose up -d` starts all four containers
- [ ] `docker compose ps` shows all four services as `Up` or `healthy`
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok","service":"api"}`
- [ ] `docker compose exec postgres psql -U videosearch videosearch -c "\dt"` lists: videos, frames, detections, known_persons, person_embeddings, unknown_clusters, face_detections
- [ ] `docker compose exec postgres psql -U videosearch videosearch -c "SELECT column_name FROM information_schema.columns WHERE table_name='face_detections';"` includes `unknown_cluster_id` and `match_tier`
- [ ] `docker compose exec postgres psql -U videosearch videosearch -c "SELECT indexname, reloptions FROM pg_indexes WHERE indexname LIKE '%hnsw%';"` shows two indexes with `{m=32,ef_construction=128}`

## must_haves

- All four services start without errors after `docker compose up -d`
- Schema has `face_detections.unknown_cluster_id UUID REFERENCES unknown_clusters(id)` from day 1
- Schema has `face_detections.match_tier TEXT CHECK (match_tier IN ('confident', 'probable'))` from day 1
- `unknown_clusters` table exists with UUID primary key
- Both HNSW indexes (person_embeddings, face_detections) use m=32, ef_construction=128
- postgres service starts with `hnsw.ef_search=64`
- InsightFace buffalo_l is in the Docker image (not downloaded at container startup)
- `.env.example` has `FACE_MATCH_HIGH_THRESHOLD=0.65` and `FACE_MATCH_LOW_THRESHOLD=0.50`
- `docs/operations.md` documents the 4 GB swap file requirement with exact commands

## threat_model

### Threats

| Threat | Category | Mitigation |
|--------|----------|------------|
| [HIGH] Postgres password in `.env` committed to git | Information Disclosure | `.env` must be in `.gitignore`; only `.env.example` is committed; plan executor must verify `grep .env .gitignore` returns a match |
| [HIGH] MinIO credentials in environment passed to all services | Information Disclosure | Credentials are env-var only (never in source code); Docker secrets not required for v1 single-host deployment but worth noting as a future hardening step |
| [MEDIUM] `docker-entrypoint-initdb.d` script runs on every fresh volume | Tampering | Schema is idempotent on fresh DB via `CREATE EXTENSION IF NOT EXISTS`; `UNIQUE` constraints prevent duplicate ingestion of existing data |
| [LOW] Memory limit of 5 GB on ingestion-worker | Denial of Service | Documented swap file (4 GB) mitigates OOM; limit is set deliberately to protect host stability |
| [LOW] External `home-infra` network exposes postgres to other containers on same network | Elevation of Privilege | Postgres is not port-mapped to host (no `ports:` on postgres service); only reachable inside Docker network |

---

<output>
After all tasks complete, create `.planning/phases/01-foundation/01-SUMMARY.md` with:
- Services started successfully (yes/no)
- Schema verified (list of tables confirmed)
- HNSW index params confirmed (m=32, ef_construction=128)
- Any deviations from the plan
</output>
