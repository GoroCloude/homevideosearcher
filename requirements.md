# Video Search System – Requirements

## 1. Project Overview

A self-hosted video search system that indexes video files by detecting objects (cars, people, animals) and recognizing specific known faces (family members). Users can search their video library to find moments where specific people or objects appear.

**Deployment target:** Ubuntu server (shumov.eu infrastructure), Docker Compose, CPU-only inference (i5-6200, 8 GB RAM).

**Primary user:** Single-user / family use case. No multi-tenancy required.

---

## 2. Goals & Non-Goals

### Goals
- Index existing video library stored in MinIO
- Detect objects per frame: people, vehicles, animals (COCO classes)
- Recognize a small set (5–20) of known faces with high precision
- Provide a web UI to search by person, object class, date range, and video
- Jump directly to the timestamp in the video where a match occurred
- Allow enrolling new faces by uploading reference images

### Non-Goals (v1)
- Real-time / live stream analysis
- Mobile app (web UI only, responsive design sufficient)
- Multi-user authentication beyond a single shared login
- Audio analysis / speech recognition
- Re-identification across non-face body features
- Cloud deployment

---

## 3. Tech Stack (fixed)

| Layer | Technology |
|---|---|
| Object storage | MinIO (already running) |
| Workflow orchestration | n8n (already running) |
| Frame extraction | FFmpeg |
| Object detection | YOLOv8 (Ultralytics, `yolov8n.pt` or `yolov8s.pt`) |
| Face detection + recognition | **InsightFace** (`buffalo_l` model pack: SCRFD detector + ArcFace recognizer) |
| Database | PostgreSQL 16 + `pgvector` extension |
| Backend API | FastAPI (Python 3.11+) |
| Frontend | React 18 + Vite + TypeScript |
| Reverse proxy / TLS | Cloudflare Tunnel (already in place) |
| Containerization | Docker + Docker Compose |
| Python deps mgmt | `uv` or `pip` with pinned `requirements.txt` |

---

## 4. System Architecture

```
                  ┌─────────────────────────────────────────────────────┐
                  │                  Existing infra                      │
                  │   ┌─────────┐    ┌──────────┐    ┌────────────────┐ │
                  │   │ MinIO   │    │   n8n    │    │ Cloudflare     │ │
                  │   │ videos/ │    │workflows │    │   Tunnel       │ │
                  │   └─────────┘    └──────────┘    └────────────────┘ │
                  └────────┬────────────┬──────────────────┬────────────┘
                           │            │                  │
       ┌───────────────────┼────────────┼──────────────────┼────────────────┐
       │                   ▼            ▼                  ▼                │
       │           ┌──────────────────────────────┐  ┌─────────────────┐   │
       │           │   ingestion-worker (Python)  │  │   api (FastAPI) │   │
       │           │   - FFmpeg frame extract     │  │   - search      │   │
       │           │   - YOLOv8 detection         │  │   - enroll face │   │
       │           │   - InsightFace recognition  │  │   - serve frames│   │
       │           │   - writes to Postgres       │  └────────┬────────┘   │
       │           └──────────────┬───────────────┘           │            │
       │                          │                           │            │
       │                          ▼                           ▼            │
       │                  ┌───────────────────────────────────────┐        │
       │                  │  PostgreSQL 16 + pgvector             │        │
       │                  │  - videos, frames, detections, faces  │        │
       │                  │  - known_persons + face embeddings    │        │
       │                  └───────────────────────────────────────┘        │
       │                                                                    │
       │                  ┌───────────────────────────────────────┐        │
       │                  │  web (React + Vite, static via nginx) │        │
       │                  └───────────────────────────────────────┘        │
       │                                                                    │
       │              New stack: docker-compose.yml                         │
       └────────────────────────────────────────────────────────────────────┘
```

### Data flow

1. **Ingestion trigger**: n8n watches a MinIO bucket (or webhook from upload) and POSTs `{video_uri, video_id}` to `ingestion-worker`.
2. **Frame extraction**: FFmpeg extracts 1 frame per second + scene-change frames into a temp directory. Frames are uploaded to MinIO under `frames/{video_id}/{ts_ms}.jpg`.
3. **Object detection**: YOLOv8 runs on each frame, emits class + bbox + confidence.
4. **Face pipeline**: For every `person` detection (or full frame, see §6.3), InsightFace runs SCRFD to find faces, then ArcFace to compute 512-dim embedding. Each embedding is matched against `known_persons` via cosine similarity in pgvector (`<=>` operator). If similarity ≥ threshold, the face is labeled with the person's name; otherwise stored as `unknown`.
5. **Persistence**: Detections + face matches written to Postgres with foreign keys to video and frame.
6. **Search**: User queries via React UI → FastAPI → SQL with filters → returns matching frames with thumbnails and deep links to the video timestamp.

---

## 5. Data Model

PostgreSQL schema. Run with `pgvector` extension enabled.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE videos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minio_key       TEXT NOT NULL UNIQUE,           -- e.g. "videos/2025/clip01.mp4"
    filename        TEXT NOT NULL,
    duration_sec    NUMERIC,
    width           INT,
    height          INT,
    fps             NUMERIC,
    recorded_at     TIMESTAMPTZ,                    -- from EXIF / filename / user
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'pending' -- pending | processing | done | failed
);

CREATE TABLE frames (
    id              BIGSERIAL PRIMARY KEY,
    video_id        UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    ts_ms           INT NOT NULL,                   -- timestamp within the video
    minio_key       TEXT NOT NULL,                  -- "frames/{video_id}/{ts_ms}.jpg"
    UNIQUE (video_id, ts_ms)
);
CREATE INDEX ON frames (video_id, ts_ms);

CREATE TABLE detections (
    id              BIGSERIAL PRIMARY KEY,
    frame_id        BIGINT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    class_name      TEXT NOT NULL,                  -- 'person', 'car', 'dog', ...
    confidence      REAL NOT NULL,
    bbox_x1         INT, bbox_y1 INT,
    bbox_x2         INT, bbox_y2 INT
);
CREATE INDEX ON detections (class_name);
CREATE INDEX ON detections (frame_id);

CREATE TABLE known_persons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per enrollment image. A person should have several (5-10) for robustness.
CREATE TABLE person_embeddings (
    id              BIGSERIAL PRIMARY KEY,
    person_id       UUID NOT NULL REFERENCES known_persons(id) ON DELETE CASCADE,
    embedding       vector(512) NOT NULL,           -- InsightFace ArcFace is 512-dim
    source_image    TEXT,                           -- MinIO key of the enrollment photo
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON person_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE face_detections (
    id              BIGSERIAL PRIMARY KEY,
    frame_id        BIGINT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    bbox_x1         INT, bbox_y1 INT,
    bbox_x2         INT, bbox_y2 INT,
    det_score       REAL,                           -- detector confidence
    embedding       vector(512) NOT NULL,
    matched_person_id UUID REFERENCES known_persons(id) ON DELETE SET NULL,
    match_similarity REAL                           -- cosine similarity to best match
);
CREATE INDEX ON face_detections USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON face_detections (matched_person_id);
CREATE INDEX ON face_detections (frame_id);
```

**Embedding normalization:** Always L2-normalize embeddings before storing so cosine distance is meaningful. InsightFace's `get_embedding` returns normalized embeddings when called via the `FaceAnalysis` app and using `face.normed_embedding`.

---

## 6. Module Specifications

### 6.1 `ingestion-worker` (Python service)

**Responsibilities:** Pull a job, process one video end-to-end, write results to Postgres and MinIO.

**Entry point:** FastAPI endpoint `POST /ingest` with body `{"minio_key": "videos/clip.mp4"}`. Also expose `POST /ingest/batch` to scan a MinIO prefix and enqueue all videos.

**Internals:**
- Use a background task queue. **Start simple** with FastAPI `BackgroundTasks`; add Celery + Redis only if backlog grows.
- Idempotent: if the video's `minio_key` already exists with status `done`, skip unless `?force=true`.
- Update `videos.status` as it progresses: `pending → processing → done | failed`.
- On failure, store error message in a `videos.error_message` column (add this to the schema).

**Frame extraction (FFmpeg):**
```bash
ffmpeg -i input.mp4 \
  -vf "fps=1,scale='min(1280,iw)':-2" \
  -q:v 3 \
  -f image2 \
  frame_%06d.jpg
```
Compute timestamp per frame: `ts_ms = frame_index * 1000` (since fps=1). For scene-change frames, parse FFmpeg's `showinfo` filter output to get `pts_time`.

**YOLOv8 usage:**
```python
from ultralytics import YOLO
model = YOLO("yolov8n.pt")  # downloads on first run; cache in a Docker volume

# Process in batches for throughput
results = model(frame_paths, imgsz=640, conf=0.35, classes=ALLOWED_CLASS_IDS)
```
Restrict to COCO classes the user cares about. Configurable via env var `YOLO_CLASSES` (comma-separated names). Default set:
`person, bicycle, car, motorcycle, bus, truck, cat, dog, horse, sheep, cow, bird`.

**InsightFace usage:**
```python
from insightface.app import FaceAnalysis

app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=0, det_size=(640, 640))

faces = app.get(frame_bgr)   # numpy BGR image
for f in faces:
    bbox = f.bbox            # [x1, y1, x2, y2]
    score = f.det_score
    emb = f.normed_embedding # already L2-normalized, shape (512,)
```
**Important:** InsightFace's `FaceAnalysis` already runs its own detector (SCRFD), so you do **not** need to crop using YOLO's person bbox first. Run InsightFace on the full frame. YOLO's `person` detections are still stored separately because they answer "is there a person?" even when no face is visible (back turned, far away).

**Face matching** (in SQL, against pgvector):
```sql
SELECT pe.person_id, 1 - (pe.embedding <=> $1::vector) AS similarity
FROM person_embeddings pe
ORDER BY pe.embedding <=> $1::vector
LIMIT 1;
```
Apply threshold (default `0.5` cosine similarity, configurable). If below threshold, store face with `matched_person_id = NULL`.

**Concurrency:** Single worker process is fine for v1 on the i5-6200. Set ONNX Runtime thread count via `OMP_NUM_THREADS=4`. Do not run YOLO and InsightFace in parallel on the same CPU — process them sequentially per frame.

---

### 6.2 `api` (FastAPI)

REST endpoints. JSON in/out, OpenAPI auto-generated at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/videos` | List videos with status, paginated |
| `GET` | `/videos/{id}` | Video metadata + summary (counts per class, persons found) |
| `GET` | `/videos/{id}/stream` | 302 redirect to a presigned MinIO URL for playback |
| `POST` | `/ingest` | Enqueue a video for processing |
| `GET` | `/persons` | List known persons with enrollment count |
| `POST` | `/persons` | Create person `{name}` |
| `DELETE` | `/persons/{id}` | Remove person and all their embeddings |
| `POST` | `/persons/{id}/enroll` | Upload 1–N images; compute embeddings; reject if no face or >1 face detected |
| `GET` | `/persons/{id}/appearances` | List frames where this person appears |
| `POST` | `/search` | Main search endpoint, see body below |
| `GET` | `/frames/{id}/image` | 302 to presigned MinIO URL |

**Search request body:**
```json
{
  "video_ids":     ["..."],           // optional filter
  "classes":       ["person", "car"], // optional, OR-combined
  "person_ids":    ["..."],           // optional, OR-combined
  "include_unknown_faces": false,
  "date_from":     "2025-01-01",
  "date_to":       "2025-12-31",
  "min_confidence": 0.4,
  "page": 1,
  "page_size": 50
}
```
**Response:** list of `{frame_id, video_id, ts_ms, thumbnail_url, detections: [...], faces: [...]}` plus `total`, `page`, `page_size`. Group consecutive frames (same video, ≤3 s gap) on the **frontend**, not the backend — keeps the API simple.

**Auth:** Single shared bearer token from env var `API_TOKEN`. Middleware that rejects requests without the right `Authorization: Bearer ...` header. Skip auth on `/health` and `/docs` only in development.

---

### 6.3 `web` (React + Vite + TypeScript)

**Pages:**
- **Search** (default): filter sidebar (persons multi-select, object classes multi-select, date range, video selector). Result grid of frame thumbnails. Clicking a thumbnail opens a modal with full frame and a "Play in video" button that opens the video at `ts_ms`.
- **Videos**: table of all videos with status, duration, count of detections, indexing date. Button to re-ingest.
- **People**: list of enrolled persons. Per person: name, thumbnail collage of enrollment images, count of appearances, delete button. "Add person" flow: name + drag-and-drop 5–10 images.
- **Settings**: API token entry (stored in `localStorage`), API base URL.

**State management:** React Query (`@tanstack/react-query`) for server state. No global store needed.

**Video playback:** `<video>` element with `currentTime = ts_ms / 1000`. Source = `/videos/{id}/stream` (which 302s to MinIO presigned URL).

**Styling:** Tailwind CSS. Keep it utilitarian — this is a tool, not a marketing site.

---

## 7. Configuration

All services configured via environment variables. Provide a `.env.example`.

```
# Postgres
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=videosearch
POSTGRES_USER=videosearch
POSTGRES_PASSWORD=change-me

# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET_VIDEOS=videos
MINIO_BUCKET_FRAMES=frames
MINIO_BUCKET_ENROLLMENT=enrollment
MINIO_USE_SSL=false

# Models
YOLO_MODEL=yolov8n.pt
YOLO_CONFIDENCE=0.35
YOLO_CLASSES=person,bicycle,car,motorcycle,bus,truck,cat,dog,horse,sheep,cow,bird
INSIGHTFACE_MODEL=buffalo_l
FACE_MATCH_THRESHOLD=0.5
FRAME_SAMPLE_FPS=1

# API
API_TOKEN=generate-a-long-random-string
API_CORS_ORIGINS=https://search.shumov.eu

# Misc
OMP_NUM_THREADS=4
LOG_LEVEL=INFO
```

---

## 8. Docker Compose Layout

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    volumes: [pgdata:/var/lib/postgresql/data, ./db/init:/docker-entrypoint-initdb.d:ro]

  ingestion-worker:
    build: ./services/ingestion-worker
    depends_on: [postgres]
    volumes: [model-cache:/root/.cache, ./tmp:/tmp/work]
    deploy:
      resources:
        limits: { memory: 5g }

  api:
    build: ./services/api
    depends_on: [postgres]
    ports: ["8000:8000"]

  web:
    build: ./services/web
    ports: ["8080:80"]
```

MinIO and n8n are **not** in this compose file — they run in the existing stack. Reference them via the existing Docker network (`external: true`).

---

## 9. n8n Integration

Two workflows:

1. **Video ingestion trigger**
   - Trigger: MinIO event on `videos/` bucket (`s3:ObjectCreated:*`) OR scheduled scan every 10 min.
   - Action: HTTP POST to `http://api:8000/ingest` with `{minio_key}`.

2. **Daily summary** (optional, nice-to-have)
   - Trigger: cron, daily at 08:00.
   - Action: query API for new appearances of family members in the last 24 h, send Telegram message.

---

## 10. Performance Targets

On the i5-6200 / 8 GB / CPU-only:

| Operation | Target |
|---|---|
| Frame extraction (1080p, 1 fps) | ~5–10× realtime |
| YOLOv8n per frame (640px) | ≤ 0.3 s |
| InsightFace per frame (1–3 faces) | ≤ 1.0 s |
| End-to-end indexing | ~0.3–0.5× realtime |

A 1-hour video → ~2–3 hours processing. Acceptable for batch / overnight.

**Memory:** YOLO ~0.5 GB, InsightFace ~1.5 GB, Postgres ~1 GB, OS + buffers ~2 GB → leaves headroom on 8 GB but is tight. Keep batch sizes small. Consider a swap file (4 GB) as safety net.

---

## 11. Testing & Acceptance

### Unit tests
- Embedding match logic with synthetic vectors
- YOLO class filtering
- API filter combinations

### Integration tests
- Ingest a 10-second test video with known content (provide a fixture in `tests/fixtures/`); assert exact counts of detections and faces.
- Enroll a face, ingest a video containing that face, assert the person is matched.

### Acceptance criteria for v1
- [ ] Can enroll a person with 5+ images via web UI
- [ ] Can ingest a video from MinIO via API call
- [ ] Search returns correct frames when filtering by an enrolled person
- [ ] Search returns correct frames when filtering by `car` or `dog`
- [ ] Combined filter (person AND class) works
- [ ] Clicking a result plays the video at the right timestamp (±1 s)
- [ ] Re-ingesting a video does not produce duplicate rows
- [ ] Service survives a restart without losing in-progress state (in-progress videos re-queue)

---

## 12. Repository Layout

```
video-search-system/
├── docker-compose.yml
├── .env.example
├── README.md
├── db/
│   └── init/
│       └── 001_schema.sql
├── services/
│   ├── ingestion-worker/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app/
│   │   │   ├── main.py            # FastAPI app
│   │   │   ├── pipeline.py        # orchestration
│   │   │   ├── frames.py          # FFmpeg wrapper
│   │   │   ├── detect.py          # YOLO wrapper
│   │   │   ├── faces.py           # InsightFace wrapper
│   │   │   ├── db.py              # asyncpg pool, queries
│   │   │   ├── storage.py         # MinIO client
│   │   │   └── config.py
│   │   └── tests/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── routers/
│   │   │   │   ├── videos.py
│   │   │   │   ├── persons.py
│   │   │   │   ├── search.py
│   │   │   │   └── frames.py
│   │   │   ├── db.py
│   │   │   ├── storage.py
│   │   │   ├── auth.py
│   │   │   └── schemas.py         # Pydantic models
│   │   └── tests/
│   └── web/
│       ├── Dockerfile
│       ├── package.json
│       ├── vite.config.ts
│       ├── tailwind.config.js
│       └── src/
│           ├── main.tsx
│           ├── App.tsx
│           ├── api/client.ts
│           ├── pages/
│           │   ├── Search.tsx
│           │   ├── Videos.tsx
│           │   ├── People.tsx
│           │   └── Settings.tsx
│           └── components/
└── docs/
    ├── architecture.md
    └── operations.md
```

---

## 13. Implementation Order (suggested for Claude Code)

Build it in this sequence, each step independently runnable / testable:

1. **Repo scaffolding** + `docker-compose.yml` with just `postgres` running. Verify connection.
2. **DB schema** as a migration in `db/init/001_schema.sql`. Verify with `psql`.
3. **`ingestion-worker` skeleton**: FastAPI app, `/health`, MinIO client, DB pool. No ML yet.
4. **Frame extraction module**: takes a video, produces frames in MinIO, writes `frames` rows.
5. **YOLO integration**: detect objects, write `detections` rows. Test on one video.
6. **InsightFace integration**: detect + embed faces, write `face_detections` rows (no matching yet).
7. **Enrollment + matching**: `known_persons`, `person_embeddings`, match in pgvector. Hook into pipeline.
8. **`api` service**: read-only endpoints first (`/videos`, `/search`).
9. **`api` write endpoints**: `/persons`, `/persons/{id}/enroll`, `/ingest`.
10. **`web` frontend**: Settings → People → Search → Videos pages, in that order.
11. **n8n workflow** for auto-ingest of new MinIO uploads.
12. **Hardening**: auth middleware, error handling, retry logic, basic metrics endpoint.

Each step ends with a runnable demo and a short note in `README.md`.

---

## 14. Open Questions for the User

Resolve these before starting implementation:

1. Where are the videos today — already in MinIO, or on disk to be uploaded?
2. Roughly how many hours of video total, and how many new hours per week?
3. Acceptable processing latency for a new upload — minutes, or "by next morning is fine"?
4. Should `unknown` faces be clustered (so you can later label "this recurring stranger is Uncle Tom") or just stored individually? (Recommend: cluster in v2, store individually in v1.)
5. Privacy: should enrollment images be deletable separately from the person record, or is "delete person" sufficient?
6. Do you want a "delete this detection / this face" admin action in the UI for false positives?

---

## 15. Notes on InsightFace specifically

- Use the **`buffalo_l`** model pack. It bundles SCRFD-10GF (detector) and a strong ArcFace recognizer producing 512-dim embeddings. `buffalo_s` is faster but noticeably less accurate; not worth it for a family-recognition use case where false matches are annoying.
- First run downloads weights (~280 MB) into `~/.insightface/models/`. Cache this in a Docker volume so rebuilds don't re-download.
- Use `face.normed_embedding`, not `face.embedding`. The normed version is L2-normalized and is what cosine similarity expects.
- SCRFD detects faces down to ~20 px. For frames with very small faces (people far away), expect misses — that's a fundamental resolution problem, not a model fix.
- Set `providers=["CPUExecutionProvider"]` explicitly. If you ever add a GPU, switch to `CUDAExecutionProvider`.
- `det_size=(640, 640)` is a good default. Larger → more small faces caught, but slower.
- Threshold guidance for `buffalo_l` cosine similarity: `≥ 0.5` is a confident match, `0.4–0.5` is borderline, `< 0.4` is almost certainly a different person. Tune on your own data.