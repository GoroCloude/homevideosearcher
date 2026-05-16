# Requirements: HomeVideoSearcher

**Defined:** 2026-05-16
**Core Value:** Automatically surface unknown faces from home camera footage and notify via daily Telegram digest

## v1 Requirements

### Infrastructure

- [ ] **INFRA-01**: Docker Compose stack with postgres (pgvector/pgvector:0.8.2-pg16), ingestion-worker, api, and web services
- [ ] **INFRA-02**: PostgreSQL schema with pgvector HNSW index (m=32, ef_construction=128, ef_search=64) for 512-dim face embeddings
- [ ] **INFRA-03**: `unknown_cluster_id` column on `face_detections` from day 1 (not a later migration)
- [ ] **INFRA-04**: Two-tier face match threshold encoded in schema/config: ≥0.65 = confident, 0.50–0.65 = probable
- [ ] **INFRA-05**: `unknown_clusters` table with stable UUIDs (never recreated — only updated incrementally)
- [ ] **INFRA-06**: Environment config via `.env` file; `.env.example` provided
- [ ] **INFRA-07**: Model cache in Docker volume (InsightFace buffalo_l, ~280 MB) — baked at build time, not downloaded at startup
- [ ] **INFRA-08**: Swap file (4 GB) documented in ops guide for 8 GB RAM constraint

### Ingestion Pipeline

- [ ] **INGEST-01**: `POST /ingest` endpoint accepts `{minio_key}` and processes one video end-to-end
- [ ] **INGEST-02**: `POST /ingest/batch` scans a MinIO prefix and enqueues all videos
- [ ] **INGEST-03**: FFmpeg extracts frames at 1 fps + scene-change frames; only frames with detections stored to MinIO
- [ ] **INGEST-04**: Idempotent: re-ingesting a `done` video skips unless `?force=true`
- [ ] **INGEST-05**: Video status tracked: `pending → processing → done | failed` with error message on failure
- [ ] **INGEST-06**: In-progress videos re-queue on service restart (no data loss)

### Object Detection

- [ ] **DETECT-01**: YOLOv8n (or YOLO11n) detects COCO objects per frame; configurable class filter via `YOLO_CLASSES` env var
- [ ] **DETECT-02**: Default COCO classes: `person, bicycle, car, motorcycle, bus, truck, cat, dog, horse, sheep, cow, bird`
- [ ] **DETECT-03**: YOLO and InsightFace run sequentially per frame (never parallel — memory constraint)
- [ ] **DETECT-04**: Detections written to `detections` table with class, confidence, and bounding box

### Face Recognition

- [ ] **FACE-01**: InsightFace buffalo_l (SCRFD detector + ArcFace) runs on every frame; stores 512-dim `normed_embedding`
- [ ] **FACE-02**: Face matching against `known_persons` via pgvector cosine similarity; two-tier threshold applied
- [ ] **FACE-03**: Unmatched faces stored with `matched_person_id = NULL` and `match_tier = NULL`
- [ ] **FACE-04**: Matched faces above confident threshold labeled in `face_detections`
- [ ] **FACE-05**: YOLO person detections and InsightFace face detections are stored independently (YOLO covers "person with no visible face"; InsightFace covers face embedding)

### Face Enrollment

- [ ] **ENROLL-01**: `POST /persons` creates a known person entry
- [ ] **ENROLL-02**: `POST /persons/{id}/enroll` accepts 1–N images; rejects if no face or >1 face detected; rejects if det_score < 0.7
- [ ] **ENROLL-03**: At least 5 enrollment images recommended (validated in UI); more = better robustness
- [ ] **ENROLL-04**: `DELETE /persons/{id}` removes the person and all embeddings
- [ ] **ENROLL-05**: After enrolling a new person, `POST /persons/{id}/rematch` retroactively re-scans all stored face embeddings and updates matches (single SQL UPDATE — no re-ingest)

### Unknown Face Clustering

- [ ] **CLUSTER-01**: Nightly batch job clusters all `matched_person_id = NULL` embeddings using HDBSCAN (`metric='euclidean'`, `algorithm='boruvka_kdtree'`, `min_cluster_size=3`)
- [ ] **CLUSTER-02**: Cluster assignment is incremental — existing cluster UUIDs are preserved; only new faces are assigned to existing or new clusters
- [ ] **CLUSTER-03**: Each cluster has a stable UUID, a representative face (highest `det_score` + sharpest image), and an appearance count
- [ ] **CLUSTER-04**: `POST /cluster/run` endpoint triggers clustering on demand (inside api service, not a separate container)
- [ ] **CLUSTER-05**: When a user promotes a cluster to a known person, all cluster member embeddings are retroactively re-matched

### Search API

- [ ] **SEARCH-01**: `POST /search` filters by: `video_ids`, `classes`, `person_ids`, `include_unknown_faces`, `date_from`, `date_to`, `min_confidence`, `page`, `page_size`
- [ ] **SEARCH-02**: Response includes `{frame_id, video_id, ts_ms, thumbnail_url, detections, faces}` plus pagination
- [ ] **SEARCH-03**: `GET /videos/{id}/stream` returns 302 redirect to presigned MinIO URL (1 hour TTL)
- [ ] **SEARCH-04**: `GET /frames/{id}/image` returns 302 redirect to presigned MinIO frame thumbnail URL
- [ ] **SEARCH-05**: Single shared bearer token auth (`API_TOKEN` env var); `/health` and `/docs` exempt

### Telegram Notifications

- [ ] **NOTIF-01**: Nightly digest sent via Telegram Bot API: unknown face clusters that appeared in the past 24 h
- [ ] **NOTIF-02**: Digest uses `sendMediaGroup` (single album ≤10 photos) — avoids rate limits (20 msgs/min/chat)
- [ ] **NOTIF-03**: Each album entry shows: cluster representative thumbnail, appearance count, videos/dates seen
- [ ] **NOTIF-04**: Digest only sent when there are new unknown faces — no message if nothing new
- [ ] **NOTIF-05**: Telegram Bot token and chat ID configured via env vars

### Web UI

- [ ] **WEB-01**: **Search page** (default): filter sidebar (persons multi-select, object classes, date range, video selector); results grid; click thumbnail → modal with "Play in video" button at correct `ts_ms`
- [ ] **WEB-02**: **Videos page**: table of all videos with status, duration, detection counts, ingestion date; "Re-ingest" button
- [ ] **WEB-03**: **People page**: enrolled persons with thumbnail collage, appearance count, delete button; "Add person" flow with drag-and-drop image upload (5–10 images)
- [ ] **WEB-04**: **Unknown Clusters page**: grid of unknown face clusters with representative thumbnail, appearance count; "Enroll as person" action; "Mark as noise/ignore" action
- [ ] **WEB-05**: **Settings page**: API token (stored in localStorage), API base URL
- [ ] **WEB-06**: State management via TanStack Query v5 (React Query); no global store
- [ ] **WEB-07**: Styling via Tailwind CSS v3; utilitarian, not marketing

### n8n Automation

- [ ] **N8N-01**: n8n workflow: MinIO bucket event (`s3:ObjectCreated:*` on `videos/`) triggers `POST /ingest`
- [ ] **N8N-02**: Polling fallback: scheduled scan every 10 minutes for videos not yet triggered

## v2 Requirements

### Enhanced Clustering

- **CLUSTER-V2-01**: Manual cluster merge (two clusters → one person)
- **CLUSTER-V2-02**: Cluster split detection (same person aging over years → multiple clusters)
- **CLUSTER-V2-03**: Body re-identification (gait, clothing) for persons without visible face

### Notifications

- **NOTIF-V2-01**: Configurable per-person alert (e.g., "alert immediately if Uncle Tom appears, daily digest for others")
- **NOTIF-V2-02**: Push notification via PWA (no dependency on Telegram)

### Performance

- **PERF-V2-01**: OpenVINO export for YOLO11n (~2–3× CPU speedup, no accuracy loss)
- **PERF-V2-02**: Multi-video parallel ingestion (requires CPU headroom validation first)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time / live stream analysis | i5-6200 too slow for real-time; overnight batch is acceptable; live needs GPU |
| Mobile app | Responsive web UI covers family use case |
| Multi-user auth | Single shared login sufficient for family |
| Audio analysis / speech recognition | Not relevant to security or family search |
| Cloud deployment | Self-hosted only by design |
| RTSP camera integration | Cameras write to disk; MinIO import is the integration point |
| Face re-ID by body features | Face is sufficient for v1; body re-ID is error-prone without GPU |
| HTTPS/TLS in stack | Cloudflare Tunnel handles TLS termination externally |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 – INFRA-08 | Phase 1 | Pending |
| INGEST-01 – INGEST-06 | Phase 2 | Pending |
| DETECT-01 – DETECT-04 | Phase 3 | Pending |
| FACE-01 – FACE-05 | Phase 3 | Pending |
| ENROLL-01 – ENROLL-05 | Phase 4 | Pending |
| SEARCH-01 – SEARCH-05 | Phase 5 | Pending |
| WEB-01 – WEB-07 | Phase 6 | Pending |
| N8N-01 – N8N-02 | Phase 7 | Pending |
| CLUSTER-01 – CLUSTER-05 | Phase 8 | Pending |
| NOTIF-01 – NOTIF-05 | Phase 9 | Pending |
| INGEST-02 (batch), SEARCH hardening | Phase 10 | Pending |

**Coverage:**
- v1 requirements: 51 total
- Mapped to phases: 51
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-16*
*Last updated: 2026-05-16 after initial definition + research synthesis*
