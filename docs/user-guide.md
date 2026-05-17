# HomeVideoSearcher — User Guide

This guide covers how to build and run the solution, enroll known faces,
and ingest your home camera footage.

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [First-Time Setup](#2-first-time-setup)
3. [Building and Starting the Stack](#3-building-and-starting-the-stack)
4. [Enrolling Known Faces](#4-enrolling-known-faces)
5. [Ingesting Videos](#5-ingesting-videos)
6. [Checking Results](#6-checking-results)
7. [Day-to-Day Operations](#7-day-to-day-operations)
8. [Troubleshooting](#8-troubleshooting)
9. [What Comes Next](#9-what-comes-next)

---

## 1. System Requirements

| Item | Minimum | Notes |
|------|---------|-------|
| OS | Ubuntu 22.04 / 24.04 | Tested on bare-metal and VMs |
| CPU | Dual-core x86_64 | Tested on Intel i5-6200 |
| RAM | 8 GB | 4 GB swap **required** (see below) |
| Disk | 50 GB+ | SSD recommended for the video archive |
| Docker | 24+ | `docker compose` v2 (not `docker-compose` v1) |
| Network | Home-infra Docker network | MinIO and n8n must already be running on it |

### Why 4 GB swap is required

The ingestion worker loads two ML models at startup:

| Model | RAM footprint |
|-------|--------------|
| YOLOv8n | ~0.5 GB |
| InsightFace buffalo_l | ~1.5 GB |
| PostgreSQL + OS | ~2 GB |
| Peak during frame processing | up to 7.5 GB |

Without swap the Linux OOM killer will terminate the ingestion worker silently.

```bash
# Run once on the Ubuntu host (as root)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make it survive reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verify
free -h   # should show ~4G in the Swap row
```

---

## 2. First-Time Setup

### 2.1 Create the Docker network

MinIO and n8n must already be running on the `home-infra` network.
If you have not created it yet:

```bash
docker network create home-infra
# If the network already exists this returns an error — that is fine.
```

### 2.2 Configure environment variables

```bash
cp .env.example .env
nano .env   # or your preferred editor
```

The variables you **must** change before the first start:

| Variable | What to set |
|----------|-------------|
| `POSTGRES_PASSWORD` | Any strong password |
| `MINIO_ACCESS_KEY` | Your MinIO access key |
| `MINIO_SECRET_KEY` | Your MinIO secret key |
| `MINIO_ENDPOINT` | `minio:9000` (or your MinIO hostname:port on home-infra) |
| `API_TOKEN` | Long random secret — `openssl rand -hex 32` |

Leave the face threshold variables at their defaults unless you have a specific reason:

```dotenv
FACE_MATCH_HIGH_THRESHOLD=0.65   # ≥ 0.65 → confident match (labelled)
FACE_MATCH_LOW_THRESHOLD=0.50    # 0.50–0.65 → probable match (flagged for review)
```

> ⚠️ **Do not lower `FACE_MATCH_HIGH_THRESHOLD` below 0.60** without testing against your
> own footage. Low-resolution camera frames produce false positives at 0.5.

### 2.3 Create MinIO buckets

The ingestion worker expects two MinIO buckets. Create them if they do not exist:

```bash
# Using the MinIO CLI (mc) — replace alias with your MinIO alias
mc mb myminio/videos
mc mb myminio/frames
```

Or create them via the MinIO web console at `http://<your-server>:9001`.

---

## 3. Building and Starting the Stack

### 3.1 Build images

```bash
docker compose build
```

> **First build takes 10–15 minutes.** The ingestion-worker image downloads and bakes
> the InsightFace buffalo_l model (~280 MB) into the image layer so container startup
> is fast on every subsequent run.

You only need to rebuild when you change a `Dockerfile` or `requirements.txt`.

### 3.2 Start the stack

```bash
docker compose up -d
```

### 3.3 Verify all services are healthy

```bash
docker compose ps
```

Expected output — all services should show `healthy` or `running`:

```
NAME                  STATUS
homevideosearcher-postgres-1          healthy
homevideosearcher-ingestion-worker-1  running
homevideosearcher-api-1               running
homevideosearcher-web-1               running
```

Check the health endpoints:

```bash
curl http://localhost:8001/health   # ingestion-worker → {"status":"ok","service":"ingestion-worker"}
curl http://localhost:8000/health   # api              → {"status":"ok"}
```

### 3.4 Watch startup logs

The ingestion-worker loads both ML models at startup. Watch the sequence:

```bash
docker compose logs -f ingestion-worker
```

Expected startup sequence (takes ~30–60 seconds on i5-6200):

```
INFO  Loading YOLO model: yolov8n.pt
INFO  YOLO active classes: person,bicycle,car,... → IDs: [0, 1, 2, ...]
INFO  YOLO model ready
      [2-second pause — memory spike stagger]
INFO  Loading InsightFace buffalo_l (2s after YOLO to avoid RSS spike)
INFO  InsightFace buffalo_l loaded successfully
INFO  Application startup complete.
```

If you do not see "InsightFace buffalo_l loaded successfully" the model was not baked
into the image. Rebuild with `docker compose build --no-cache ingestion-worker`.

### 3.5 Stop the stack

```bash
docker compose down          # stops containers, keeps data
docker compose down -v       # ⚠ DELETES the Postgres volume — all data lost
```

---

## 4. Enrolling Known Faces

Enrollment teaches the system who your family members (or anyone you want identified)
are. Every enrolled person gets one or more 512-dimensional face embeddings stored in
the database. During video ingestion, every detected face is compared against these
embeddings using cosine similarity.

### How many photos to enroll?

| Photos | Quality |
|--------|---------|
| 1–2 | Minimum — will work but may miss the person in challenging angles |
| 5–10 | **Recommended** — covers different lighting, angles, expressions |
| 10+ | Best recall — particularly for cameras with poor night-vision |

**Good enrollment photo criteria:**
- Single person in the frame (solo portrait — no group photos)
- Face clearly visible, not obscured by sunglasses, masks, or hats
- Good lighting — avoid harsh backlighting
- At least 200×200 px face area in the image
- Variety: different angles, lighting conditions, with/without glasses

### 4.1 Install the enrollment script dependencies (host machine)

The enrollment script runs on your **host** (not inside Docker) and connects to the
Postgres container directly on `localhost:5432`.

```bash
# Create a virtual environment for the enrollment tools
python3.11 -m venv .venv-enroll
source .venv-enroll/bin/activate    # Windows: .venv-enroll\Scripts\activate

pip install insightface==0.7.3 onnxruntime==1.19.2 \
            psycopg2-binary python-dotenv opencv-python-headless
```

> **Note:** InsightFace will download the buffalo_l model (~280 MB) on first run
> to `~/.insightface/models/buffalo_l/`. This is separate from the Docker image copy.

### 4.2 Enroll a person

```bash
# Enroll from individual photos
python scripts/enroll_face.py --name "Anna" \
    --photos photos/anna_kitchen.jpg photos/anna_garden.jpg photos/anna_birthday.jpg

# Enroll from a whole folder (picks up .jpg .jpeg .png)
python scripts/enroll_face.py --name "Max" --photos photos/max/

# Add more photos to an existing person later
python scripts/enroll_face.py --name "Anna" --photos photos/anna_new_glasses.jpg
```

Example output:

```
Loading InsightFace buffalo_l… (first call takes ~5 seconds)
Created person 'Anna' (id=3f8a1c2d-…)
  Processing anna_kitchen.jpg… ✅ enrolled
  Processing anna_garden.jpg…  ✅ enrolled
  Processing anna_birthday.jpg… ✅ enrolled

Done. Enrolled 3 embedding(s) for 'Anna'.

ℹ  Already-processed videos will NOT be automatically re-matched.
   Phase 2 adds `POST /persons/{id}/rematch` for retroactive matching.
   For now, re-ingest videos using ?force=true to pick up the new person.
```

### 4.3 View enrolled persons

```bash
python scripts/enroll_face.py --list
```

```
Name                      Embeddings  Enrolled at               ID
────────────────────────────────────────────────────────────────────────────────
Anna                               3  2026-05-17 09:12:33       3f8a1c2d-…
Max                                7  2026-05-16 18:44:01       a1b2c3d4-…
```

### 4.4 Remove a person

```bash
python scripts/enroll_face.py --remove "Anna"
# Prompts for confirmation, then deletes person + all their embeddings
```

After removal, `face_detections` rows that were matched to this person will have
`matched_person_id = NULL` (ON DELETE SET NULL in the schema).

### 4.5 Common enrollment errors

| Error | Cause | Fix |
|-------|-------|-----|
| `No face detected` | Photo too small, blurry, or obscured | Use a clear, well-lit solo portrait |
| `2 faces detected` | Group photo | Crop to a single person before enrolling |
| `det_score 0.43 too low` | Low quality / low resolution | Use a higher-res photo (≥ 200×200 px face) |
| `Cannot read image` | Unsupported format or corrupt file | Convert to JPEG first |

### 4.6 How face matching works during ingest

When a video is ingested, for every frame where YOLO detected a **person**:

1. InsightFace SCRFD detects faces in the full frame
2. ArcFace extracts a 512-dim `normed_embedding` for each face
3. pgvector HNSW cosine search finds the closest enrolled person embedding
4. The two-tier threshold is applied:

```
similarity ≥ 0.65  →  match_tier = 'confident'  →  assigned to person
0.50 ≤ sim < 0.65  →  match_tier = 'probable'   →  assigned but flagged for review
similarity < 0.50  →  match_tier = NULL          →  unknown face (enters cluster pool)
```

Unknown faces (no match) are saved to the database and will be grouped into clusters
by the HDBSCAN clustering job added in Phase 3.

---

## 5. Ingesting Videos

### 5.1 Upload a video to MinIO

The ingestion worker reads videos from your MinIO `videos/` bucket.
Upload your camera footage first:

```bash
# Using mc CLI
mc cp /path/to/recording.mp4 myminio/videos/2024/05/recording.mp4

# Or via MinIO web console at http://<your-server>:9001
```

Supported formats: `.mp4`, `.mov`, `.avi`, `.mkv`

### 5.2 Ingest a single video

```bash
curl -X POST http://localhost:8001/ingest \
     -H "Content-Type: application/json" \
     -d '{"minio_key": "videos/2024/05/recording.mp4"}'
```

Response:

```json
{"status": "queued", "video_id": "a1b2c3d4-..."}
```

The video is processed in the background. Processing time depends on length and
content — expect roughly 1–3 minutes per minute of footage on an i5-6200.

### 5.3 Ingest a whole folder at once

```bash
curl -X POST http://localhost:8001/ingest/batch \
     -H "Content-Type: application/json" \
     -d '{"prefix": "videos/2024/05/"}'
```

Response:

```json
{"status": "ok", "queued": 12, "skipped": 3, "prefix": "videos/2024/05/"}
```

`skipped` = videos already processed (status = `done`). Use `"force": true` to re-process:

```bash
curl -X POST http://localhost:8001/ingest/batch \
     -H "Content-Type: application/json" \
     -d '{"prefix": "videos/2024/05/", "force": true}'
```

### 5.4 Monitor ingestion progress

```bash
# Live logs
docker compose logs -f ingestion-worker

# Check video status directly in Postgres
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT filename, status, error_message
FROM videos
ORDER BY ingested_at DESC
LIMIT 20;"
```

Status values:

| Status | Meaning |
|--------|---------|
| `pending` | Waiting to be processed |
| `processing` | Currently being processed |
| `done` | Fully processed — detections in DB |
| `failed` | Error — check `error_message` column |

### 5.5 Re-ingest a video (force reprocess)

If you enrolled new persons after a video was already processed and want the
new person matched against that footage:

```bash
curl -X POST "http://localhost:8001/ingest?force=true" \
     -H "Content-Type: application/json" \
     -d '{"minio_key": "videos/2024/05/recording.mp4"}'
```

> **Note:** `?force=true` deletes existing frames and detections for that video
> and reprocesses from scratch. It does NOT duplicate rows.

### 5.6 What the pipeline does per video

```
Download video from MinIO (temp file)
    ↓
FFmpeg: extract frames
    • Scene-change detection (threshold 0.3) — captures interesting moments
    • Plus fixed 1 fps — ensures no long gaps are missed
    ↓
For each batch of 8 frames:
    YOLO → detect persons, cars, animals, etc.
    If person detected in frame:
        InsightFace → detect faces → extract embeddings → match vs enrolled persons
    If ANY detection found → upload frame to MinIO frames/ bucket
                           → store detections + face_detections in DB
    ↓
Update video status → 'done'
```

Only frames with at least one detection are stored — blank frames are discarded.

---

## 6. Checking Results

### 6.1 Count detections

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT
    v.filename,
    COUNT(DISTINCT f.id)  AS frames_stored,
    COUNT(DISTINCT d.id)  AS yolo_detections,
    COUNT(DISTINCT fd.id) AS face_detections
FROM videos v
LEFT JOIN frames f   ON f.video_id = v.id
LEFT JOIN detections d ON d.frame_id = f.id
LEFT JOIN face_detections fd ON fd.frame_id = f.id
WHERE v.status = 'done'
GROUP BY v.filename
ORDER BY v.filename;"
```

### 6.2 See who was recognised

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT
    kp.name,
    fd.match_tier,
    COUNT(*) AS face_hits
FROM face_detections fd
JOIN known_persons kp ON kp.id = fd.matched_person_id
GROUP BY kp.name, fd.match_tier
ORDER BY kp.name, fd.match_tier;"
```

### 6.3 Count unknown faces (not matched to any enrolled person)

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT COUNT(*) AS unknown_faces
FROM face_detections
WHERE matched_person_id IS NULL;"
```

### 6.4 Inspect a specific detection

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT
    f.minio_key   AS frame,
    f.ts_ms / 1000.0 AS seconds_in,
    fd.det_score,
    fd.match_similarity,
    fd.match_tier,
    kp.name       AS matched_person
FROM face_detections fd
JOIN frames f ON f.id = fd.frame_id
LEFT JOIN known_persons kp ON kp.id = fd.matched_person_id
ORDER BY f.ts_ms
LIMIT 20;"
```

---

## 7. Day-to-Day Operations

### Restart the stack (e.g. after server reboot)

```bash
docker compose up -d
```

Any video that was `processing` when the worker last stopped is automatically
reset to `pending` and requeued on startup — no data is lost.

### Update the stack after a code change

```bash
docker compose build ingestion-worker   # rebuild only the changed service
docker compose up -d --no-deps ingestion-worker
```

### Adjust which objects YOLO detects

Edit `.env` and change `YOLO_CLASSES`, then restart the worker:

```dotenv
# Example: only detect persons and cars
YOLO_CLASSES=person,car
```

```bash
docker compose restart ingestion-worker
```

Re-ingest existing videos with `?force=true` if you want detections updated.

### Reduce memory usage on low-RAM machines

Reduce batch size in `.env` (default 8 → try 4):

```dotenv
YOLO_BATCH_SIZE=4
```

Then restart the worker: `docker compose restart ingestion-worker`

### View HNSW index health

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT indexname, reloptions
FROM pg_indexes
JOIN pg_class ON indexname = relname
WHERE indexname LIKE '%hnsw%';"
```

Expected output confirms `m=32, ef_construction=128`:

```
      indexname              |          reloptions
─────────────────────────────+───────────────────────────────────────
 person_embeddings_hnsw_idx  | {m=32,ef_construction=128}
 face_detections_hnsw_idx    | {m=32,ef_construction=128}
```

---

## 8. Troubleshooting

### Worker is OOM-killed (exits silently)

```bash
free -h             # check swap is active
docker compose logs ingestion-worker | tail -20
```

If swap is missing, re-run the `fallocate` commands from Section 1.
Alternatively reduce `YOLO_BATCH_SIZE` to `4` in `.env`.

### Video stuck in `processing` after restart

The worker automatically resets `processing → pending` on startup.
If it does not happen:

```bash
# Manual reset
docker compose exec postgres psql -U videosearch videosearch -c "
UPDATE videos SET status = 'pending' WHERE status = 'processing';"
```

### Video fails with error

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT filename, error_message FROM videos WHERE status = 'failed';"
```

Common causes:
- **MinIO connection error** — check `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` in `.env`
- **FFmpeg error** — video file is corrupt or unsupported codec
- **OOM during processing** — increase swap or reduce `YOLO_BATCH_SIZE`

### InsightFace model missing

```bash
docker compose build --no-cache ingestion-worker
```

### No faces detected in videos

Check that YOLO is detecting persons first — InsightFace only runs on frames
where YOLO found at least one `person`:

```bash
docker compose exec postgres psql -U videosearch videosearch -c "
SELECT class_name, COUNT(*) FROM detections GROUP BY class_name ORDER BY 2 DESC;"
```

If no `person` rows appear, YOLO is not detecting any people. Try lowering
`YOLO_CONFIDENCE` to `0.25` in `.env` and re-ingest.

### Enrollment script cannot connect to Postgres

The script connects to `localhost:5432` by default. Make sure the Postgres
container port is exposed. Check `docker-compose.yml` — the postgres service
should have `ports: ["5432:5432"]`. If it does not, add it temporarily for
enrollment and remove after.

---

## 9. What Comes Next

Phase 1 is the foundation. Here is what the subsequent phases add:

| Phase | What it adds |
|-------|-------------|
| **Phase 2** | `POST /persons/{id}/enroll` API (upload photos via HTTP, no script needed) · `POST /persons/{id}/rematch` (retroactively re-match all existing face detections after enrolling a new person — no re-ingest needed) · `POST /search` API (search by person, object, date) · `GET /videos/{id}/stream` (presigned MinIO URLs) · n8n workflows (auto-ingest on MinIO upload) |
| **Phase 3** | HDBSCAN clustering of unknown faces · daily Telegram digest with album of unknown faces · stable cluster UUIDs · `POST /cluster/run` endpoint |
| **Phase 4** | React web UI — search page, persons page, unknown clusters page, settings |

To proceed:
```
/gsd-plan-phase 2
```
