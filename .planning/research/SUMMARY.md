# Research Summary: HomeVideoSearcher

**Synthesized:** 2025-05-16  
**Sources read:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md, PROJECT.md  
**Overall Confidence:** HIGH — all four research files grounded in live docs, PyPI, Docker Hub, and framework source. Sole MEDIUM area is HDBSCAN epsilon tuning, which requires empirical calibration on real footage.

---

## Recommended Stack (with deltas from requirements.md)

| Component | requirements.md | Research recommendation | Delta / reason |
|-----------|----------------|------------------------|----------------|
| Object detection | `yolov8n.pt` | **Keep `yolov8n.pt` for v1** | YOLO11n is strictly better (22% fewer params, higher mAP) but is a one-line env-var swap. Defer upgrade until accuracy proves insufficient on real footage. |
| Face recognition | InsightFace `buffalo_l` | **Keep** | Still the best CPU ArcFace implementation; `insightface==0.7.3`, Python 3.11 only (not 3.12+). Pin tightly. |
| Unknown-face clustering | DBSCAN (implied) | **Replace with HDBSCAN** | `sklearn.cluster.HDBSCAN` (scikit-learn ≥ 1.3, built-in). Avoids epsilon tuning, handles variable density, uses O(n log n) memory with `algorithm='boruvka_kdtree'` + `metric='euclidean'` on L2-normalized vectors (equivalent to cosine distance). No new dependency. |
| pgvector index params | default | **m=32, ef_construction=128, ef_search=64** | Default m=16 is suboptimal for 512-dim at this recall requirement. Apply from Day 1 in schema. |
| Python package manager | pip | **uv** | `uv==0.11.14` — dramatically faster Docker builds; replaces pip in Dockerfiles. |
| Tailwind CSS | unspecified | **Pin to v3** | v4 has breaking config changes; pin explicitly to avoid silent breakage. |
| TanStack Query | v4 syntax implied | **v5 API** | `useQuery()` is object-form only in v5; confirm all examples use v5 syntax. |
| Telegram integration | n8n sends telegram | **Python-telegram-bot in api service** | `python-telegram-bot==22.*` handles message construction and photo albums directly in the API; n8n calls `POST /cluster/run` then `POST /digest/send`. This keeps formatting logic in Python, not in n8n's limited node ecosystem. |
| Clustering dependency | not in requirements.md | **`scikit-learn==1.8.0`** | No extra package; HDBSCAN is built-in since 1.3. |

**Pinned versions (additions/corrections to requirements.md):**

```
ultralytics==8.4.51
insightface==0.7.3
onnxruntime==1.26.0          # CPU-only, NOT onnxruntime-gpu
fastapi==0.136.1
asyncpg==0.31.0
pgvector==0.4.2
python-multipart>=0.0.20     # Required for enrollment file upload — MISSING from requirements.md
minio==7.2.20
scikit-learn==1.8.0          # HDBSCAN built-in
python-telegram-bot==22.*    # MISSING from requirements.md
opencv-python-headless>=4.10

# Docker images — pin exact, not floating tags:
pgvector/pgvector:0.8.2-pg16
python:3.11-slim-bookworm
node:22-alpine
nginx:1.27-alpine
```

---

## Architecture Overview

### Component Map

```
External infra (already running):
  MinIO ──── n8n ──── Cloudflare Tunnel

New containers (docker-compose.yml):
  ingestion-worker (FastAPI)       api (FastAPI)            web (nginx)
  ├─ FFmpeg frame extraction       ├─ /videos, /search      └─ React 18 SPA
  ├─ YOLOv8n detection             ├─ /persons (enrollment)
  ├─ InsightFace embedding         ├─ /frames (presigned URLs)
  ├─ pgvector cosine match         ├─ POST /cluster/run  ← NEW
  └─ Memory limit: 5 GB           ├─ POST /digest/send  ← NEW
                                   └─ python-telegram-bot
                   │                         │
                   └──────────┬──────────────┘
                              ▼
                    PostgreSQL 16 + pgvector
                    + face_clusters table  ← NEW
```

**Critical architectural rule:** `ingestion-worker` and `api` share no code and do not call each other. n8n is the orchestrator between them.

### Processing Pipeline (per video)

```
1. n8n MinIO event → POST /ingest
2. Download video from MinIO → /tmp/work/{video_id}/
3. FFmpeg: 1 fps + scene-change frames → upload to MinIO frames/ bucket + write frames table
4. YOLO batch (8–16 frames at a time) → write detections table
5. InsightFace (frame-by-frame, only when YOLO detected a 'person') → write face_detections
   ├─ Cosine search against person_embeddings (HNSW index)
   ├─ similarity ≥ 0.65 → matched_person_id = <UUID>
   ├─ similarity 0.50–0.65 → probable_person_id = <UUID>, low_confidence = TRUE (NOT in unknown pool)
   └─ similarity < 0.50 → matched_person_id = NULL (genuine unknown, enters cluster pool)
6. Cleanup /tmp/work/{video_id}/
7. Set videos.status = 'done'
```

**Model loading:** Both models load once at worker startup (`lifespan` event). Never re-load per frame. Add 2-second sleep between YOLO load and InsightFace load to avoid simultaneous RSS spike.

### Clustering Strategy

- **NOT per-video.** Cluster the entire unknown pool nightly — signal only emerges across multiple videos.
- **Triggered by n8n cron at 02:00:** `POST /cluster/run` (hosted inside `api` service, not a separate container).
- **Algorithm:** HDBSCAN with `algorithm='boruvka_kdtree'`, `metric='euclidean'`, `min_cluster_size=3`, `min_samples=2`, `cluster_selection_epsilon=0.55` (calibrate empirically).
- **Incremental after v1 launch:** New unknown faces are assigned to nearest existing cluster centroid if distance < ε; otherwise new cluster. Full re-cluster only on admin request. This preserves stable cluster UUIDs and user labels.
- **Schema additions needed (migration, not init script):**

```sql
CREATE TABLE face_clusters (
    id              SERIAL PRIMARY KEY,
    label           INT NOT NULL,
    person_name     TEXT,                        -- user-assigned label, nullable
    face_count      INT NOT NULL DEFAULT 0,
    representative_embedding vector(512),
    thumbnail_minio_key TEXT,
    first_seen_at   TIMESTAMPTZ,
    last_seen_at    TIMESTAMPTZ,
    suppress_alerts BOOLEAN NOT NULL DEFAULT FALSE,  -- "dismiss as expected" flag
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_updated_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE face_detections
    ADD COLUMN cluster_id         INT REFERENCES face_clusters(id) ON DELETE SET NULL,
    ADD COLUMN low_confidence     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN probable_person_id UUID REFERENCES known_persons(id) ON DELETE SET NULL;
```

### Telegram Digest Design

- n8n triggers `POST /api/cluster/run` (wait 200 OK), then `POST /api/digest/send`
- API service builds and sends via `python-telegram-bot==22.*`
- **Message 1 (always):** Summary text — known person appearances + unknown cluster count
- **Message 2 (if unknowns exist):** `sendMediaGroup` of up to 10 cluster face-crop thumbnails (200×200px JPEG, < 1 MB each, stored in MinIO `thumbnails/` prefix)
- **Alert logic:** Only notify on clusters where `first_seen_at > NOW() - 24h` (new clusters) or clusters not flagged `suppress_alerts`
- **Rate limit safety:** Max 2 Telegram API calls (summary text + one media group album). Well within 20 msg/min per chat limit.
- **Silence is signal:** When no unknowns, send one short "All quiet" message.

### Video Streaming

- `GET /videos/{id}/stream` → 302 redirect to MinIO presigned URL (1h TTL)
- MinIO serves bytes directly to browser; API is not in the bandwidth path
- CORS must be configured on MinIO for `search.shumov.eu` (GET + HEAD, expose `Accept-Ranges`, `Content-Range`)
- **React Query `staleTime`** must be ≤ 55 minutes to prevent expired presigned URL hits

---

## Critical Design Decisions

Decisions that must be made before coding starts. Defaulting them incorrectly creates refactoring debt.

### 1. Two-Tier Face Match Threshold (implement before any data is written)

| Tier | Similarity range | Action |
|------|-----------------|--------|
| Confident match | ≥ 0.65 | `matched_person_id = person`, included in Telegram digest |
| Probable match | 0.50–0.65 | `probable_person_id = person`, `low_confidence = TRUE`, excluded from digest and unknown cluster pool |
| Unknown | < 0.50 | `matched_person_id = NULL`, enters HDBSCAN pool |

Start threshold values at 0.65 / 0.50. Validate against real footage in week 1 and adjust. Store as env vars: `FACE_MATCH_HIGH_THRESHOLD=0.65` and `FACE_MATCH_LOW_THRESHOLD=0.50`.

### 2. Stable Cluster UUIDs from Day 1

Design `face_clusters` with a stable primary key and `person_name` field before the first clustering run. Use incremental assignment (nearest centroid) after initial launch — never full re-cluster silently. User labels survive nightly re-runs.

### 3. Docker Day 1 Checklist (must be done before any containers run)

- [ ] Bake model downloads into Docker build (`RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"` and InsightFace equivalent) — do NOT download at runtime
- [ ] `depends_on: condition: service_healthy` + postgres healthcheck in compose file
- [ ] External Docker network created before `docker compose up` (`docker network create home-infra`)
- [ ] 4 GB swap file on Ubuntu host (`fallocate -l 4G /swapfile`)
- [ ] Alembic migration tooling from Phase 1 (never rely on `docker-entrypoint-initdb.d` after initial deploy)
- [ ] Recovery query at ingestion-worker startup (reset `status = 'processing'` rows older than 1 hour)
- [ ] HNSW index created with `m=32, ef_construction=128` (not default m=16)
- [ ] `SET hnsw.ef_search=64` in postgresql.conf

### 4. MinIO Selective Frame Storage (prevents disk exhaustion)

Do NOT store frames for every extracted second. Only upload a frame to MinIO if it has at least one detection (YOLO confidence ≥ 0.5 or any face). Reduces frame storage by 60–80% for typical home footage. This must be enforced from the first frame written — retrofitting is painful.

### 5. Enrollment Minimums

- Minimum 3 enrollment images (API enforces, returns 422 if fewer)
- Show UI warning if < 5 images ("accuracy is reduced")
- Reject if `det_score < 0.7`, face bbox < 80×80px, or multiple faces detected
- Store `normed_embedding` (not `embedding`) exclusively; wrap in a `normalize_embedding()` utility called on every embedding before any DB write

---

## Phase Order Recommendation

Based on the dependency graph from ARCHITECTURE.md, consolidated into logical milestones for a roadmapper:

### Phase 1 — Infrastructure Foundation
**Delivers:** Running Docker Compose, database schema, MinIO connectivity  
**Covers:** Compose scaffold (postgres + services), DB schema with correct HNSW params, MinIO client wrapper, healthcheck wiring, Alembic setup, model bake into Dockerfile, swap file, external network  
**Must avoid:** DI-1 (runtime model download), DI-2 (depends_on not ready), DI-3 (no migrations), DI-5 (external network missing)  
**Research flag:** Standard patterns — no deep research needed

### Phase 2 — Ingestion Pipeline (Video → Frames → DB)
**Delivers:** End-to-end video processing without ML; frames in MinIO + DB  
**Covers:** ingestion-worker FastAPI skeleton, FFmpeg frame extraction with sliding-window (not all-at-once), selective frame upload (detections-only), frames table writes  
**Must avoid:** MEM-2 (all frames to disk before processing), SS-2 (unbounded MinIO growth)  
**Research flag:** Standard patterns

### Phase 3 — ML Detection (YOLO + InsightFace)
**Delivers:** Object and face detections in DB; unknown faces flagged  
**Covers:** YOLO batch integration (8–16 frames), InsightFace integration (gated on YOLO person detection), two-tier threshold logic, embedding normalization utility, face_detections writes  
**Must avoid:** FR-1 (threshold 0.5 too permissive), FR-3 (InsightFace on all frames), FR-4 (using raw embedding instead of normed), MEM-1 (simultaneous model load OOM), MEM-4 (ONNX thread contention)  
**Research flag:** May need phase research for OMP thread tuning on real hardware

### Phase 4 — Face Enrollment + Matching
**Delivers:** Known person enrollment; retroactive matching against existing embeddings  
**Covers:** known_persons + person_embeddings schema, enrollment API with quality validation (FR-2, FR-5), cosine matching in pipeline, pgvector HNSW index, "scan historical footage" endpoint  
**Must avoid:** FR-2 (single enrollment image), FR-5 (unvalidated enrollment quality)  
**Research flag:** Standard patterns

### Phase 5 — Search API + Video Streaming
**Delivers:** Full query API; video playback with timestamp seek  
**Covers:** GET /videos, POST /search (person + date + class filters), presigned URL generation (1h TTL), CORS config on MinIO  
**Must avoid:** SS-3 (presigned URL expiry / React Query staleTime mismatch)  
**Research flag:** Standard patterns

### Phase 6 — Web UI
**Delivers:** Usable product — first end-to-end user-facing milestone  
**Covers:** React 18 + Vite + TanStack Query v5 + Tailwind v3, Search page, Videos page, People page (enrollment), Settings  
**Must avoid:** TanStack Query v4/v5 API mismatch, Tailwind v3/v4 config mismatch  
**Research flag:** Standard patterns

### Phase 7 — n8n Automation
**Delivers:** Hands-free ingestion; videos auto-processed on MinIO upload  
**Covers:** n8n Workflow 1 (MinIO event → POST /ingest), n8n Workflow 2 (scheduled scan fallback)  
**Must avoid:** Unreliable MinIO event triggers (build poll fallback as parallel path)  
**Research flag:** Standard patterns

### Phase 8 — Unknown Face Clustering
**Delivers:** Grouped unknowns; recurring strangers identified; cluster labeling UI  
**Covers:** face_clusters migration, HDBSCAN job in api service, stable UUID clustering, Clusters UI page, "Enroll from cluster" action  
**Must avoid:** CL-1 (DBSCAN OOM at scale), CL-2 (epsilon too high = one giant cluster), CL-3 (cluster ID drift), CL-4 (known faces polluting unknown pool)  
**Research flag:** Likely needs phase research for HDBSCAN epsilon calibration on actual footage

### Phase 9 — Telegram Digest
**Delivers:** Daily notification; core security value delivered to mobile  
**Covers:** python-telegram-bot integration, POST /digest/send, n8n Workflow 3 (02:00 cron), face-crop thumbnail generation (200×200px to MinIO thumbnails/), sendMediaGroup album  
**Must avoid:** NOT-1 (rate limiting), NOT-2 (full-frame > 10 MB), NOT-3 (notification fatigue / suppress_alerts)  
**Research flag:** Standard patterns (Telegram API is well-documented)

### Phase 10 — Bulk Import + Hardening
**Delivers:** Production-ready system; existing video archive imported  
**Covers:** POST /ingest/batch (MinIO prefix scan), auth middleware (Bearer token), error_message column, metrics endpoint, Docker memory limits review, REINDEX schedule  
**Research flag:** Standard patterns

---

## Top Pitfalls to Mitigate Early

1. **Face threshold 0.5 causes false positives (FR-1 + CL-4)** — Use two-tier thresholds (≥ 0.65 confident, 0.50–0.65 probable) from the first pipeline commit. Faces in the probable tier must not enter the unknown clustering pool. Getting this wrong means the Telegram digest falsely identifies family members as unknowns and vice versa. Fix before any real data is written.

2. **HDBSCAN must replace DBSCAN; use boruvka_kdtree (CL-1)** — DBSCAN's naive distance matrix is O(n²) memory. At 50,000 face embeddings that's 10 GB — instant OOM on 8 GB RAM. Use `HDBSCAN(algorithm='boruvka_kdtree', metric='euclidean')` on L2-normalized vectors. This is a design decision, not an optimization; wrong algorithm choice makes clustering non-functional at scale.

3. **Stable cluster UUIDs must be designed before first clustering run (CL-3)** — If clustering truncates and rewrites `face_clusters` on every nightly run, user-assigned labels ("this is the delivery driver") disappear the next morning. Design incremental assignment (nearest centroid) and `suppress_alerts` flag before shipping Phase 8. Retrofitting cluster identity is a data migration nightmare.

4. **Docker Day 1 checklist (DI-1, DI-2, DI-3, DI-5)** — Four Docker pitfalls that cause first-deploy failures and data loss: (a) models downloaded at runtime risk partial files; (b) `depends_on` without healthcheck causes connection-refused crashes on startup; (c) no migration tooling means schema changes require wiping the DB; (d) external network not pre-created causes cryptic startup error. Address all four before writing a single line of application code.

5. **MinIO selective frame storage from Day 1 (SS-2)** — At 1 fps, a 24/7 home camera produces 13–36 GB of JPEG frames per day. Only store frames with detections (YOLO or face confidence ≥ 0.5). This policy must be encoded in `frames.py` from the first frame written. Adding it retroactively requires scanning and deleting thousands of already-stored objects.

6. **Telegram digest: one album, 10-photo cap, 1h presigned URL TTL (NOT-1, NOT-2, SS-3)** — Use a single `sendMediaGroup` call with ≤ 10 cluster thumbnails (200×200px JPEG stored in MinIO `thumbnails/` prefix). Full frame images exceed Telegram's 10 MB limit. Presigned URLs used in UI thumbnails must have TTL ≤ 1h matched by React Query `staleTime` — mismatched cache leads to broken image icons with no visible error.

---

## Open Questions

These cannot be resolved from documentation alone — they require empirical testing on real hardware and real footage, or a decision from the user.

| # | Question | Impact | Resolution method |
|---|----------|--------|-------------------|
| 1 | **What is the correct face match threshold for this specific camera setup?** Requirements say 0.5; research says start at 0.65. The real value depends on camera resolution, night-mode grain, and subject variation. | High — wrong value → either false positives (alert fatigue) or false negatives (missed recognition) | Log similarity histograms in week 1; tune `FACE_MATCH_HIGH_THRESHOLD` env var empirically |
| 2 | **What is the correct HDBSCAN epsilon for this footage?** Research recommends `cluster_selection_epsilon=0.55` (euclidean on L2-normalized ≈ cosine 0.70). Security camera footage compresses inter-person embedding distances vs. studio photos. | High — wrong value → all unknowns in one cluster or no clusters at all | Manual validation: label 50–100 unknown face crops, tune until cluster output matches manual labels |
| 3 | **Will the OMP_NUM_THREADS=4 cause PostgreSQL starvation on i5-6200?** Research recommends 2–3 threads for ONNX Runtime, not 4. | Medium — may cause asyncpg timeouts mid-ingestion | Monitor `top` during first full-batch run; adjust `OMP_NUM_THREADS` if postgres threads starve |
| 4 | **How many unknown faces will be in the library at scale?** The HDBSCAN precomputed-matrix approach OOMs at ~50K embeddings. Boruvka_kdtree is O(n log n). | Medium — affects clustering implementation choice | Estimate: count of unknown detections after initial archive import |
| 5 | **Frame retention policy — how long to keep frames in MinIO?** 30 days was suggested but not decided. User preference needed. | Low-medium — affects disk planning | User decision: storage budget vs. lookback window |
| 6 | **n8n MinIO event triggers vs. polling fallback — which is primary?** MinIO webhooks can be unreliable in Docker networking. | Low — both are built; which one to monitor and prefer | Empirical: test MinIO webhook delivery reliability in the specific network setup |

---

## Sources (Aggregated)

- Ultralytics GitHub + YOLO11 docs (Context7): stack validation, YOLO11n vs YOLOv8n comparison
- InsightFace PyPI v0.7.3: maintenance status, buffalo_l model characteristics
- pgvector v0.8.2 GitHub + Docker Hub: HNSW parameters, halfvec, delete behavior
- scikit-learn 1.8.0 docs: HDBSCAN built-in since 1.3, boruvka_kdtree memory profile
- FastAPI v0.136.1 GitHub: lifespan events, BackgroundTasks, Pydantic v2
- python-telegram-bot v22 (Context7): sendMediaGroup, rate limits
- Telegram Bot API: 10 MB photo limit, 20 msg/min per chat, sendMediaGroup ≤ 10 items
- Frigate NVR v0.17.1 docs: unknown face handling gap, WebPush-only notifications
- Double Take, CompreFace, Shinobi, ZoneMinder: feature gap analysis
- MinIO Python SDK v7.2.20 + MinIO CORS docs: presigned URL generation, browser CORS requirements
- ArcFace paper (Deng et al., 2019): threshold sensitivity to image quality
- Docker Compose docs: depends_on service_healthy, external networks
- ONNX Runtime docs: OMP_NUM_THREADS, INTRA_OP_NUM_THREADS thread contention patterns
