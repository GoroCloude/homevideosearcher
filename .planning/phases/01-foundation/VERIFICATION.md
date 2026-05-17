---
phase: 01-foundation
verified: 2026-05-17T08:00:00Z
status: passed
score: 22/22 must-haves verified
overrides_applied: 0
re_verification: false
gaps: []
human_verification:
  - test: "docker compose up — full end-to-end smoke test"
    expected: "All four services start healthy; POST /ingest with a real MinIO video key completes end-to-end with frames in MinIO, YOLO detections and InsightFace embeddings written to PostgreSQL"
    why_human: "Cannot run Docker build + ML model download + live MinIO/PostgreSQL in a static code-only environment; requires actual hardware (i5-6200, 8 GB RAM + 4 GB swap)"
---

# Phase 1: Foundation — Verification Report

**Phase Goal:** A fully wired Docker Compose stack that ingests a video from MinIO, extracts frames, runs YOLO object detection and InsightFace face embedding, and writes all results to PostgreSQL — with the schema correct from day one (no migrations needed for clustering or two-tier thresholds).

**Verified:** 2026-05-17T08:00:00Z
**Status:** PASSED (all 22 static criteria verified; 1 human smoke-test item identified for final confirmation)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                 | Status     | Evidence                                                                 |
|----|---------------------------------------------------------------------------------------|------------|--------------------------------------------------------------------------|
| 1  | docker-compose.yml has all 4 services + home-infra external network                  | ✓ VERIFIED | Lines 1–83: postgres, ingestion-worker, api, web; `networks.home-infra.external: true` |
| 2  | postgres uses pgvector/pgvector:0.8.2-pg16 with --hnsw.ef_search=64                  | ✓ VERIFIED | `image: pgvector/pgvector:0.8.2-pg16`; `command: ["postgres","-c","hnsw.ef_search=64"]` |
| 3  | HNSW indexes with m=32, ef_construction=128 on both normed_embedding columns          | ✓ VERIFIED | 001_schema.sql lines 69–72 (person_embeddings_hnsw_idx) and 106–109 (face_detections_hnsw_idx) |
| 4  | face_detections.unknown_cluster_id UUID FK nullable                                   | ✓ VERIFIED | 001_schema.sql line 103: `unknown_cluster_id UUID REFERENCES unknown_clusters(id) ON DELETE SET NULL` — no NOT NULL |
| 5  | face_detections.match_tier CHECK ('confident','probable')                             | ✓ VERIFIED | 001_schema.sql line 102: `match_tier TEXT CHECK (match_tier IN ('confident', 'probable'))` |
| 6  | unknown_clusters table with UUID PK                                                   | ✓ VERIFIED | 001_schema.sql lines 78–86: `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` |
| 7  | Dockerfile bakes buffalo_l model (FaceAnalysis prepare in RUN layer)                  | ✓ VERIFIED | Dockerfile lines 28–33: `FaceAnalysis(name='buffalo_l').prepare(ctx_id=0, det_size=(640,640))` |
| 8  | .env.example has FACE_MATCH_HIGH_THRESHOLD and FACE_MATCH_LOW_THRESHOLD               | ✓ VERIFIED | .env.example lines 22–23: `FACE_MATCH_HIGH_THRESHOLD=0.65`, `FACE_MATCH_LOW_THRESHOLD=0.50` |
| 9  | docs/operations.md mentions 4 GB swap                                                 | ✓ VERIFIED | operations.md line 10: `## ⚠️ Required: 4 GB Swap File` with fallocate commands |
| 10 | lifespan loads YOLO → waits 2s → loads InsightFace                                    | ✓ VERIFIED | main.py lines 36, 41, 45: `load_yolo_model()` → `asyncio.sleep(2)` → `load_face_model()` |
| 11 | pipeline.py state machine: processing → done / failed with error_message              | ✓ VERIFIED | pipeline.py lines 171, 263, 277: `update_video_status("processing"/"done"/"failed", error_message=…)` |
| 12 | Crash recovery resets processing → pending on startup                                 | ✓ VERIFIED | db.py lines 118–136: `reset_stale_processing_videos()` UPDATE; called in main.py lifespan line 30 |
| 13 | Only frames WITH detections uploaded to MinIO                                         | ✓ VERIFIED | pipeline.py lines 231–233: `has_any_detection = bool(yolo_detections) or bool(face_detections); if not has_any_detection: continue` |
| 14 | POST /ingest and POST /ingest/batch endpoints in main.py                              | ✓ VERIFIED | main.py lines 82 and 137: `@app.post("/ingest")`, `@app.post("/ingest/batch")` |
| 15 | GET /health endpoint in main.py                                                       | ✓ VERIFIED | main.py line 77: `@app.get("/health")` returns `{"status":"ok","service":"ingestion-worker"}` |
| 16 | detect.py has load_yolo_model() and run_yolo_batch() with class filtering             | ✓ VERIFIED | detect.py lines 61 (`load_yolo_model`), 72 (`run_yolo_batch`), 96 (`classes=allowed_class_ids`) |
| 17 | YOLO runs in batches, not one frame at a time                                         | ✓ VERIFIED | pipeline.py lines 205–208: `for batch_start in range(0, len(frame_paths), config.YOLO_BATCH_SIZE)` |
| 18 | config.py has YOLO_CLASSES, YOLO_BATCH_SIZE, YOLO_CONFIDENCE                         | ✓ VERIFIED | config.py lines 19–26: `YOLO_CONFIDENCE`, `YOLO_CLASSES`, `YOLO_BATCH_SIZE` (see note §1) |
| 19 | faces.py uses face.normed_embedding (NOT face.embedding)                              | ✓ VERIFIED | faces.py line 76: `normed_emb = face.normed_embedding` + explicit CRITICAL comment lines 73–75 |
| 20 | Two-tier threshold: ≥0.65 → 'confident', 0.50–0.65 → 'probable', <0.50 → NULL        | ✓ VERIFIED | faces.py lines 150–157: `if similarity >= high → confident; elif >= low → probable; else → (None, sim, None)` |
| 21 | Cosine search uses pgvector: normed_embedding <=> $1::vector                          | ✓ VERIFIED | faces.py lines 138–139: `ORDER BY pe.normed_embedding <=> $1::vector LIMIT 1` |
| 22 | InsightFace only runs on frames with YOLO person detection                            | ✓ VERIFIED | pipeline.py lines 223–228: `has_person = any(d.class_name == "person" …); if has_person and face_app is not None: …` |

**Score: 22/22 truths verified**

---

### Required Artifacts

| Artifact                                          | Expected                             | Status     | Details                                          |
|---------------------------------------------------|--------------------------------------|------------|--------------------------------------------------|
| `docker-compose.yml`                              | 4 services + external network        | ✓ VERIFIED | Exists, substantive, all 4 services present      |
| `db/init/001_schema.sql`                          | Full schema incl. pgvector HNSW      | ✓ VERIFIED | 122 lines, all tables/indexes/FKs present        |
| `services/ingestion-worker/Dockerfile`            | Bakes buffalo_l at build time        | ✓ VERIFIED | 43 lines; two RUN ML-baking layers               |
| `services/ingestion-worker/app/config.py`         | Typed env vars incl. face thresholds | ✓ VERIFIED | All YOLO + face threshold vars present           |
| `services/ingestion-worker/app/main.py`           | Lifespan + 3 endpoints               | ✓ VERIFIED | Full lifespan; GET /health, POST /ingest, /ingest/batch |
| `services/ingestion-worker/app/pipeline.py`       | State machine + selective upload     | ✓ VERIFIED | Full pipeline; has_any_detection gate; run_yolo/run_insightface wired |
| `services/ingestion-worker/app/detect.py`         | YOLO batch inference + class filter  | ✓ VERIFIED | load_yolo_model, run_yolo_batch, _resolve_class_ids |
| `services/ingestion-worker/app/faces.py`          | InsightFace + pgvector two-tier match| ✓ VERIFIED | load_face_model, analyze_frame, match_face_embedding |
| `services/ingestion-worker/app/db.py`             | asyncpg pool + crash recovery        | ✓ VERIFIED | reset_stale_processing_videos, all SQL helpers   |
| `.env.example`                                    | All required env vars                | ✓ VERIFIED | 38 lines; all YOLO, face, DB, MinIO, API vars    |
| `docs/operations.md`                              | 4 GB swap + setup guide              | ✓ VERIFIED | Swap section prominent; fallocate commands       |

---

### Key Link Verification

| From                     | To                                   | Via                                              | Status     | Details                                          |
|--------------------------|--------------------------------------|--------------------------------------------------|------------|--------------------------------------------------|
| `main.py` lifespan       | `detect.load_yolo_model()`           | Direct import + assignment to `app.state.yolo`  | ✓ WIRED    | main.py lines 35–38                             |
| `main.py` lifespan       | `faces.load_face_model()`            | `asyncio.sleep(2)` + assignment to `app.state.face_app` | ✓ WIRED | main.py lines 41–45                    |
| `main.py` lifespan       | `db.reset_stale_processing_videos()` | Awaited call at startup                          | ✓ WIRED    | main.py line 30                                 |
| `pipeline.run_yolo()`    | `detect.run_yolo_batch()`            | Deferred import inside function body             | ✓ WIRED    | pipeline.py lines 80–82                         |
| `pipeline.run_insightface()` | `faces.analyze_frame()` + `faces.match_face_embedding()` | Deferred import inside function body | ✓ WIRED | pipeline.py lines 108–121     |
| `process_video` InsightFace gate | `has_person` flag             | `any(d.class_name == "person" for d in yolo_detections)` | ✓ WIRED | pipeline.py lines 223–228    |
| `faces.match_face_embedding` | `person_embeddings` (pgvector HNSW) | `normed_embedding <=> $1::vector LIMIT 1`     | ✓ WIRED    | faces.py lines 131–142                          |
| `pipeline._write_face_detections` | `face_detections` table    | asyncpg INSERT with `$7::vector` cast            | ✓ WIRED    | pipeline.py lines 319–337                       |
| `pipeline.process_video` | MinIO upload (selective)             | `has_any_detection` guard + `upload_frame()`     | ✓ WIRED    | pipeline.py lines 231–237                       |

---

### Data-Flow Trace (Level 4)

| Artifact              | Data Variable    | Source                           | Produces Real Data | Status      |
|-----------------------|------------------|----------------------------------|-------------------|-------------|
| `pipeline.py`         | `yolo_detections`| `detect.run_yolo_batch()` → real `YOLO.model()` call | Yes — batch inference on real frame images | ✓ FLOWING |
| `pipeline.py`         | `face_detections`| `faces.analyze_frame()` → `face_app.get(frame_bgr)` | Yes — InsightFace SCRFD inference on real frames | ✓ FLOWING |
| `faces.py`            | `similarity`     | `1.0 - (normed_embedding <=> $1::vector)` DB query | Yes — pgvector HNSW cosine search | ✓ FLOWING |
| `db.py`               | frame rows       | `INSERT INTO frames … RETURNING id` with ON CONFLICT | Yes — idempotent DB write | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior                                         | Method                                                  | Result        | Status  |
|--------------------------------------------------|---------------------------------------------------------|---------------|---------|
| `detect.run_yolo_batch` accepts class filter     | Code read: `model(..., classes=allowed_class_ids, ...)`  | Confirmed     | ✓ PASS  |
| `faces.match_face_embedding` applies two-tier    | Code read: if/elif/else on similarity vs high/low        | Confirmed     | ✓ PASS  |
| `reset_stale_processing_videos` writes UPDATE    | Code read: `UPDATE videos SET status='pending' WHERE status='processing'` | Confirmed | ✓ PASS |
| Selective upload gate                            | Code read: `if not has_any_detection: continue`          | Confirmed     | ✓ PASS  |
| Step 7b: live Docker stack                       | Cannot execute without running services                  | N/A           | ? SKIP — needs human |

---

### Requirements Coverage

| Requirement Group    | Status      | Evidence                                                                        |
|----------------------|-------------|---------------------------------------------------------------------------------|
| INFRA-01–08 (8)      | ✓ SATISFIED | Docker Compose stack, pgvector schema, HNSW indexes, model baking, env vars     |
| INGEST-01–06 (6)     | ✓ SATISFIED | State machine, crash recovery, FFmpeg extraction, MinIO upload, batch endpoint  |
| DETECT-01–04 (4)     | ✓ SATISFIED | YOLO loaded once, YOLO_CLASSES filter, batch inference, detections table        |
| FACE-01–05 (5)       | ✓ SATISFIED | normed_embedding, two-tier threshold, pgvector HNSW cosine, has_person gate, separate tables |

---

### Anti-Patterns Found

| File          | Pattern                                   | Severity  | Impact                                                     |
|---------------|-------------------------------------------|-----------|------------------------------------------------------------|
| `pipeline.py` | `if yolo_model is None: return [[] …]`    | ℹ️ Info   | Graceful null guard, not a stub — model is loaded at startup and passed through |
| `pipeline.py` | `if face_app is None: return []`          | ℹ️ Info   | Same — null guard for safety, not a placeholder path       |

> **No blockers found.** Both null guards are defensive coding for startup-race safety, not hollow stubs — both models are loaded in the lifespan event before any request is accepted.

---

### Commit Verification

All commits documented in SUMMARY files confirmed present in `git log`:

| Commit    | Plan | Description                                                         |
|-----------|------|---------------------------------------------------------------------|
| `f0ea07b` | 01   | chore(01-01): docker-compose.yml, .env.example, .gitignore          |
| `06d5938` | 01   | feat(01-02): db/init/001_schema.sql                                  |
| `85ee0eb` | 01   | feat(01-03): service Dockerfiles, requirements, app stubs, ops guide |
| `3e5bace` | 02   | feat(01-02): add config.py, db.py, storage.py                       |
| `a041b58` | 02   | feat(01-02): add frames.py and replace main.py                      |
| `83683ab` | 02   | feat(01-02): add pipeline.py                                        |
| `82c3477` | 03   | feat(01-03): add detect.py YOLO model wrapper                       |
| `d5a4586` | 03   | feat(01-03): wire YOLO into pipeline.py and main.py                 |
| `72e0e72` | 04   | feat(01-04): add faces.py InsightFace model loading                 |
| `19811fb` | 04   | feat(01-04): wire InsightFace into pipeline.py and main.py          |

---

### Notes

**§1 — YOLO_CONF_THRESHOLD vs YOLO_CONFIDENCE:**  
The checklist criterion references `YOLO_CONF_THRESHOLD`. The actual env var and config attribute are named `YOLO_CONFIDENCE` (set in Plan 02 and documented in Plan 03 as an intentional naming choice). This is a documentation inconsistency, not a functional gap — the variable is fully present and wired.

**§2 — "pipeline.py resets stale processing" (criterion #12):**  
The crash-recovery logic lives in `db.reset_stale_processing_videos()`, called from `main.py`'s lifespan, which is architecturally correct (startup concern belongs in entrypoint, not the pipeline module). The behavior fully satisfies the intent of the criterion.

---

### Human Verification Required

#### 1. End-to-End Live Stack Smoke Test

**Test:**
1. Create 4 GB swap: `sudo fallocate -l 4G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
2. Create external network: `docker network create home-infra`
3. Copy `.env.example` → `.env`, fill in MinIO credentials and a strong POSTGRES_PASSWORD
4. `docker compose up --build -d`
5. Wait for all services healthy: `docker compose ps`
6. Check both health endpoints: `curl http://localhost:8001/health` and `curl http://localhost:8000/health`
7. Upload a short test video to MinIO `videos/` bucket, then: `curl -X POST http://localhost:8001/ingest -H "Content-Type: application/json" -d '{"minio_key":"videos/test.mp4"}'`
8. Wait for processing to complete, then query: `SELECT status, error_message FROM videos WHERE minio_key='videos/test.mp4'`
9. Verify: `SELECT COUNT(*) FROM frames`, `SELECT COUNT(*) FROM detections`, `SELECT COUNT(*) FROM face_detections`
10. Re-ingest without force → expect `"status":"skipped"`; re-ingest with `?force=true` → expect reprocessing
11. Kill the worker mid-ingest, restart, verify the video re-queues and finishes

**Expected:** All four services start and report healthy; a real video completes the full pipeline with frames in MinIO `frames/` bucket and non-zero rows in detections/face_detections; idempotency and force-reprocess work correctly; crash recovery re-queues the interrupted video.

**Why human:** Cannot execute Docker builds, ML model downloads (~280 MB InsightFace + YOLO), or live PostgreSQL/MinIO I/O in a static code-review context. Requires actual hardware with 8 GB RAM + 4 GB swap as documented in operations.md.

---

## Gaps Summary

**No gaps found.** All 22 static verification criteria pass from source code inspection. The codebase is fully implemented — no stubs remain from Plans 01–02; Plans 03 and 04 replaced all detection/recognition stubs with real inference code.

One human verification item (live Docker smoke test) is logged above. This cannot be automated in a code-review context and is a standard pre-Phase-2 sanity check, not a blocker identified by static analysis.

---

## Recommendation

**✅ Ready to proceed to Phase 2** once the human smoke test (item 1 above) confirms the live stack runs correctly end-to-end on the target hardware. All static criteria are fully satisfied.

---

_Verified: 2026-05-17T08:00:00Z_  
_Verifier: gsd-verifier (automated static analysis)_
