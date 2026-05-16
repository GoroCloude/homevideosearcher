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

## HNSW Index Parameters

The schema uses non-default HNSW parameters for better recall at home-video scale:

| Parameter | Value | Why |
|-----------|-------|-----|
| `m` | 32 | More connections per node → higher recall (default: 16) |
| `ef_construction` | 128 | More candidates during build → better index quality (default: 64) |
| `ef_search` | 64 | More candidates during search → higher recall (set via postgres command arg) |

## Useful Commands

```bash
# View ingestion-worker logs
docker compose logs -f ingestion-worker

# Check HNSW index parameters in Postgres
docker compose exec postgres psql -U videosearch videosearch \
  -c "SELECT indexname, reloptions FROM pg_indexes JOIN pg_class ON indexname = relname WHERE indexname LIKE '%hnsw%';"

# List all tables
docker compose exec postgres psql -U videosearch videosearch -c "\dt"

# Check face_detections columns (verify unknown_cluster_id and match_tier present)
docker compose exec postgres psql -U videosearch videosearch \
  -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='face_detections' ORDER BY ordinal_position;"

# Trigger manual ingest
curl -X POST http://localhost:8001/ingest \
  -H "Content-Type: application/json" \
  -d '{"minio_key": "videos/your-clip.mp4"}'
```

## Face Recognition Thresholds

Two-tier face match thresholds (configurable via `.env`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `FACE_MATCH_HIGH_THRESHOLD` | `0.65` | Confident match — labeled + eligible for Telegram digest |
| `FACE_MATCH_LOW_THRESHOLD` | `0.50` | Probable match — stored with `match_tier='probable'`, flagged for review |

Do not lower `FACE_MATCH_HIGH_THRESHOLD` below `0.60` without validating against your
actual camera footage — low-resolution frames can produce false positives at 0.5.

## Troubleshooting

### ingestion-worker OOM-killed

1. Check swap is active: `free -h`
2. If swap is missing: run the fallocate commands above
3. Reduce `YOLO_BATCH_SIZE` (default 8 → try 4) to lower peak memory

### Postgres not healthy

```bash
docker compose logs postgres
# Look for permission errors on /var/lib/postgresql/data
```

If volume permissions are wrong:
```bash
docker compose down -v   # WARNING: destroys data
docker compose up -d
```

### InsightFace model not found

The buffalo_l model is baked into the ingestion-worker image at build time.
If it is missing, the image was built incorrectly. Rebuild:
```bash
docker compose build --no-cache ingestion-worker
```
