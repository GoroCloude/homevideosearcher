# HomeVideoSearcher

Self-hosted home security and family archive video search system.

## What It Does

- Indexes video files from MinIO (home cameras)
- Detects objects per frame: person, car, animal (YOLOv8n, COCO subset)
- Detects and embeds all faces per frame (InsightFace buffalo_l, ArcFace 512-dim)
- Recognizes enrolled family members; clusters unknown faces
- Daily Telegram digest for unknown face clusters
- Web UI: search by person, object class, date range; jump to video timestamp

## Quick Start

See [docs/operations.md](docs/operations.md) for full setup instructions.

```bash
# 1. Create swap file (required — see docs/operations.md)
# 2. Ensure home-infra network exists
docker network create home-infra

# 3. Configure
cp .env.example .env
nano .env   # set POSTGRES_PASSWORD, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, API_TOKEN

# 4. Build and start (first build ~10-15 min — bakes ML models)
docker compose build
docker compose up -d

# 5. Verify
curl http://localhost:8000/health   # api
curl http://localhost:8001/health   # ingestion-worker
```

## Stack

- **Backend:** Python 3.11, FastAPI, asyncpg
- **ML:** YOLOv8n (object detection), InsightFace buffalo_l (face recognition)
- **Storage:** PostgreSQL 16 + pgvector (HNSW), MinIO
- **Frontend:** nginx (Phase 1 placeholder; React 18 + Vite in Phase 4)
- **Infrastructure:** Docker Compose, external `home-infra` network

## Hardware

Designed for CPU-only inference: i5-6200, 8 GB RAM. Requires 4 GB swap file.
