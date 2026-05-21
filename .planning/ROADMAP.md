# Roadmap: HomeVideoSearcher

**Target:** Self-hosted system that automatically surfaces unknown faces from home camera footage and delivers a daily Telegram digest — with a web UI for search, enrollment, and cluster management.
**Milestone:** v1.0

---

## Phase 1: Foundation

**Goal:** A fully wired Docker Compose stack that ingests a video from MinIO, extracts frames, runs YOLO object detection and InsightFace face embedding, and writes all results to PostgreSQL — with the schema correct from day one (no migrations needed for clustering or two-tier thresholds).

**Requirements covered:**
- INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, INFRA-07, INFRA-08
- INGEST-01, INGEST-02, INGEST-03, INGEST-04, INGEST-05, INGEST-06
- DETECT-01, DETECT-02, DETECT-03, DETECT-04
- FACE-01, FACE-02, FACE-03, FACE-04, FACE-05

**Plans:**
1. Docker Compose + Schema — `docker-compose.yml` for postgres, ingestion-worker, api, and web services; PostgreSQL schema with pgvector HNSW index (m=32, ef_construction=128), `face_detections.unknown_cluster_id` column, `unknown_clusters` table with stable UUIDs, two-tier threshold (≥0.65 confident / 0.50–0.65 probable) in config; `.env.example`; InsightFace buffalo_l model baked into ingestion-worker image at build time
2. Ingestion Worker — FastAPI `ingestion-worker` service: `POST /ingest` processes one video end-to-end; `POST /ingest/batch` scans a MinIO prefix; FFmpeg 1-fps + scene-change frame extraction; frames uploaded to MinIO `frames/` bucket; video status state machine (`pending → processing → done | failed`); in-progress videos re-queued on restart; idempotent re-ingest guard with `?force=true` override
3. YOLO Object Detection — YOLOv8n loaded once at worker startup (`lifespan` event); configurable `YOLO_CLASSES` env var; default COCO class filter; batch inference (8–16 frames); detections written to `detections` table; YOLO and InsightFace always run sequentially (never parallel)
4. Face Recognition — InsightFace buffalo_l (SCRFD + ArcFace) loaded once at startup with 2-second post-YOLO delay; 512-dim `normed_embedding` stored per face; pgvector HNSW cosine search against `person_embeddings`; two-tier threshold applied; unmatched faces stored with `matched_person_id = NULL`; YOLO person detections and InsightFace face detections stored independently

**Status: ✅ COMPLETE**

**Done when:**
- [x] `docker compose up` starts all four services with no errors; `GET /health` returns 200 on both ingestion-worker and api
- [x] PostgreSQL schema is verified: `face_detections` has `unknown_cluster_id`; HNSW index has m=32, ef_construction=128; two-tier thresholds are present in config/schema; `unknown_clusters` table exists
- [x] `POST /ingest` with a real MinIO video key completes end-to-end: frames appear in MinIO `frames/` bucket, YOLO detections and InsightFace embeddings are written to the database
- [x] Re-ingesting a `done` video returns a skip response; `?force=true` re-processes and updates rows without duplicating them
- [x] Killing the ingestion-worker mid-video and restarting causes the video to re-queue and finish processing (no lost data, no duplicate rows)
- [x] `YOLO_CLASSES` env var controls which object classes are detected (verified by changing the list and re-ingesting)
- [x] Ops guide documents the 4 GB swap file requirement; `.env.example` covers all required vars

---

## Phase 2: Enrollment, Search API & n8n Automation

**Goal:** Users can enroll known family members, search footage by person/object/date, stream video clips at the right timestamp, and have new camera recordings automatically trigger ingestion via n8n — all protected by a shared bearer token.

**Requirements covered:**
- ENROLL-01, ENROLL-02, ENROLL-03, ENROLL-04, ENROLL-05
- SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04, SEARCH-05
- N8N-01, N8N-02

**Plans:**
1. Face Enrollment API — `POST /persons` creates a known person; `POST /persons/{id}/enroll` accepts 1–N images, rejects if no face detected, >1 face, or `det_score < 0.7`; `DELETE /persons/{id}` removes person + embeddings; `POST /persons/{id}/rematch` runs a single SQL UPDATE to retroactively match all stored face embeddings against the new person (no re-ingest)
2. Search & Stream API — `POST /search` with full filter set (video_ids, classes, person_ids, include_unknown_faces, date_from, date_to, min_confidence, page, page_size); response includes frame_id, video_id, ts_ms, thumbnail_url, detections, faces, pagination; `GET /videos/{id}/stream` returns 302 to presigned MinIO URL (1 h TTL); `GET /frames/{id}/image` returns 302 to presigned frame thumbnail URL; single bearer token auth via `API_TOKEN` env var; `/health` and `/docs` exempt from auth
3. n8n Workflows — Workflow #1: MinIO `s3:ObjectCreated:*` event on `videos/` bucket triggers `POST /ingest`; Workflow #2: scheduled poll every 10 minutes for videos not yet triggered (fallback for missed events); both workflows documented with export JSON

**Done when:**
- [ ] `POST /persons` + `POST /persons/{id}/enroll` with 5 face images creates a person; uploading a blank image or a group photo is rejected with an informative error
- [ ] `POST /search` with `person_ids` returns frames containing that person, with thumbnail URLs that resolve to actual images
- [ ] `GET /videos/{id}/stream` returns a 302 redirect to a presigned MinIO URL that plays the video at the browser
- [ ] Unauthenticated requests to `/search` and `/persons` return 401; `GET /health` and `GET /docs` return 200 without a token
- [ ] `POST /persons/{id}/rematch` after enrolling a new person updates `matched_person_id` in `face_detections` for existing embeddings — verified by querying the DB before and after (no re-ingest required)
- [ ] Uploading a new video to the MinIO `videos/` bucket triggers the n8n workflow, which calls `POST /ingest` within 60 seconds; video reaches `done` status
- [ ] Polling fallback workflow fires every 10 minutes and enqueues any video in `pending` status that was not triggered by the event

---

## Phase 3: Unknown Face Intelligence & Telegram Digest

**Goal:** Every night the system clusters all unrecognized faces across the full video library, assigns stable identities to recurring strangers, and delivers a Telegram photo album listing every new unknown cluster — so the user knows exactly who appeared without watching any footage.

**Requirements covered:**
- CLUSTER-01, CLUSTER-02, CLUSTER-03, CLUSTER-04, CLUSTER-05
- NOTIF-01, NOTIF-02, NOTIF-03, NOTIF-04, NOTIF-05

**Plans:** 3 plans

Plans:
- [x] 03-01-PLAN.md — DB migration (ignored + promoted_at columns) + HDBSCAN clustering engine (POST /cluster/run, GET /clusters, ignore/restore/promote endpoints) + main.py wiring
- [x] 03-02-PLAN.md — Telegram digest (POST /digest/send, sendMediaGroup with MinIO bytes) + n8n workflow JSON (8am cron → cluster/run → digest/send)
- [x] 03-03-PLAN.md — React UI: ClusterItem type extension, new API hooks (promote/ignore/restore), ClusterCard enroll→promote + noise button, ClustersPage collapsed Ignored section

**Done when:**
- [ ] `POST /cluster/run` groups unknown face embeddings into clusters; each cluster has a stable UUID, a representative thumbnail, and an appearance count stored in `unknown_clusters`
- [ ] Running `POST /cluster/run` a second time does not change the UUIDs of existing clusters; only new faces are assigned to existing or new clusters
- [ ] Promoting a cluster to a known person via the API updates all cluster-member `face_detections.matched_person_id` in a single operation — verified by DB query before and after
- [ ] Telegram digest arrives in the configured chat as a single photo album with representative thumbnails and captions showing appearance count and dates
- [ ] No Telegram message is sent when there are zero new unknown cluster appearances in the past 24 h
- [ ] n8n cron workflow at 02:00 calls `POST /cluster/run` then `POST /digest/send` in sequence; both succeed and the job is logged

---

## Phase 4: Web UI

**Goal:** Users can search footage, manage enrolled family members, browse and label unknown face clusters, and stream video — all from a browser, without touching the API directly.

**Requirements covered:**
- WEB-01, WEB-02, WEB-03, WEB-04, WEB-05, WEB-06, WEB-07

**Status: ✅ COMPLETE**

Plans:
- [x] 04-01-PLAN.md — API prerequisite fixes (frames auth, public MinIO, GET /videos, stream-url) + full React scaffold (Vite + Tailwind v3 + TanStack Query v5) + all API hook files
- [x] 04-02-PLAN.md — Search page: Layout shell, FrameThumbnail, VideoModal, SearchPage with filter sidebar + results grid + pagination
- [x] 04-03-PLAN.md — Library management: VideosPage (status table + Re-ingest), PeoplePage (enrollment dropzone + PersonCard), nginx ingest-api proxy
- [x] 04-04-PLAN.md — Unknown Clusters page + Settings page + Toast system + mobile responsive polish

**Done when:**
- [ ] Search page loads; filtering by a known person name returns frame thumbnails containing that person; filtering by object class "car" returns frames with car detections
- [ ] Clicking a frame thumbnail opens a modal; clicking "Play in video" opens the video stream in a new tab and seeks to the correct timestamp
- [ ] People page shows all enrolled persons; dragging 5+ images into the upload zone and submitting creates the person and reloads the person list
- [ ] Unknown Clusters page shows cluster cards with thumbnails and appearance counts; clicking "Enroll as person" prompts for a name and completes enrollment — the cluster card disappears from the unknown list
- [ ] Videos page shows all ingested videos with their current status; clicking "Re-ingest" on a `done` video re-processes it (status cycles back through processing → done)
- [ ] Setting the API token in Settings and refreshing the page keeps all pages functional (token persisted in localStorage)
- [ ] All pages render correctly at 1280 × 800 and 390 × 844 (mobile) viewport sizes

---

## Phase 5: Video Upload UI

**Goal:** Users can upload video files directly from the Videos page; each file goes to MinIO via a presigned PUT URL and ingestion starts automatically — without requiring MinIO console access.

**Requirements covered:**
- UPLOAD-01, UPLOAD-02, UPLOAD-03, UPLOAD-04, UPLOAD-05, UPLOAD-06

**Plans:** 1 plan

Plans:
- [x] 05-01-PLAN.md — Backend presigned PUT URL endpoint + storage helper + frontend VideoUploadButton component with XHR queue/progress + VideosPage integration + CORS setup script

**Done when:**
- [x] `POST /api/videos/upload-url` returns a presigned PUT URL; unauthenticated request returns 401
- [x] "Upload Video" button appears at the top-right of the Videos page
- [x] Selecting a file > 1 GB shows a toast error with zero network requests made
- [x] Upload progress (%) is visible while a file uploads directly to MinIO
- [x] Multiple files upload sequentially (second does not start before first finishes)
- [x] After upload, `POST /ingest-api/ingest` is called automatically; video appears in list with `processing`/`done` status within 10 seconds
- [x] Uploading a duplicate filename overwrites the MinIO object and re-processes it

---

## Coverage

| Requirement Group | Count | Phase |
|-------------------|-------|-------|
| INFRA-01 – INFRA-08 | 8 | 1 |
| INGEST-01 – INGEST-06 | 6 | 1 |
| DETECT-01 – DETECT-04 | 4 | 1 |
| FACE-01 – FACE-05 | 5 | 1 |
| ENROLL-01 – ENROLL-05 | 5 | 2 |
| SEARCH-01 – SEARCH-05 | 5 | 2 |
| N8N-01 – N8N-02 | 2 | 2 |
| CLUSTER-01 – CLUSTER-05 | 5 | 3 |
| NOTIF-01 – NOTIF-05 | 5 | 3 |
| WEB-01 – WEB-07 | 7 | 4 |
| UPLOAD-01 – UPLOAD-06 | 6 | 5 |
| **Total** | **58** | ✓ all mapped |

> Note: count is 52 (8+6+4+5+5+5+2+5+5+7). REQUIREMENTS.md traceability table states 51 — one may be an off-by-one in that section. All named requirements above are explicitly listed in REQUIREMENTS.md and are fully covered.

---

## Progress

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 1 — Foundation | 4 | ✅ Complete | 4/4 |
| 2 — Enrollment, Search & Automation | 3 | ✅ Complete | 3/3 |
| 3 — Intelligence & Telegram Digest | 2 | ✅ Complete | 2/2 |
| 4 — Web UI | 4 | ✅ Complete | 4/4 |
| 5 — Video Upload UI | 1 | ✅ Complete | 1/1 |

---
*Roadmap created: 2026-05-16*
