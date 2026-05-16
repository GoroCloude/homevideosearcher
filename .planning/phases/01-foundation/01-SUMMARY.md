---
phase: 1
plan: "01"
subsystem: infrastructure
tags: [docker-compose, postgresql, pgvector, schema, insightface, yolo, nginx, fastapi]
dependency_graph:
  requires: []
  provides:
    - docker-compose stack with four services
    - postgresql schema with full phase 1-3 column set
    - hnsw vector indexes on face and person embeddings
    - ingestion-worker docker image with baked ml models
    - api and ingestion-worker health endpoints
  affects:
    - all subsequent phases (schema must not change for covered columns)
tech_stack:
  added:
    - "pgvector/pgvector:0.8.2-pg16 — PostgreSQL 16 with pgvector extension"
    - "python:3.11-slim-bookworm — base for ingestion-worker and api"
    - "nginx:1.27-alpine — web placeholder (Phase 4 replaces with React)"
    - "insightface==0.7.3 — buffalo_l SCRFD + ArcFace face recognition"
    - "onnxruntime==1.26.0 — CPU ONNX inference backend"
    - "ultralytics==8.4.51 — YOLOv8n object detection"
    - "fastapi==0.136.1 + uvicorn==0.35.0 — API framework"
    - "asyncpg==0.31.0 + pgvector==0.4.2 — async PostgreSQL driver"
    - "scikit-learn==1.8.0 — HDBSCAN clustering (Phase 3)"
    - "uv==0.11.14 — fast package manager for Docker builds"
  patterns:
    - "docker-entrypoint-initdb.d for schema-on-first-start"
    - "HNSW m=32 ef_construction=128 for high-recall face search"
    - "service_healthy depends_on for postgres readiness"
    - "two-tier face threshold: FACE_MATCH_HIGH/LOW via env vars"
    - "ML models baked at Docker build time (not downloaded at startup)"
key_files:
  created:
    - docker-compose.yml
    - .env.example
    - .gitignore
    - db/init/001_schema.sql
    - services/ingestion-worker/Dockerfile
    - services/ingestion-worker/requirements.txt
    - services/ingestion-worker/app/main.py
    - services/api/Dockerfile
    - services/api/requirements.txt
    - services/api/app/main.py
    - services/web/Dockerfile
    - services/web/nginx.conf
    - docs/operations.md
    - README.md
  modified: []
decisions:
  - "Used pgvector/pgvector:0.8.2-pg16 (not floating :pg16 tag) for reproducibility"
  - "Added WORKER_PORT env var for ingestion-worker port mapping (not in plan spec — Rule 2: health endpoint unreachable without port)"
  - "Added ONNX_DISABLE_GLOBAL_THREAD_POOL=1 alongside OMP_NUM_THREADS=4 per STACK.md memory guidance"
  - "Added unknown_clusters.label TEXT column per critical_context item 5"
  - "Created services/web/nginx.conf (listed in repo layout but not in task actions)"
  - "Created ingestion-worker/app/main.py stub (Dockerfile copies app/ — build would fail without it)"
metrics:
  duration: "~15 minutes"
  completed_date: "2026-05-16"
  tasks_completed: 3
  files_created: 14
---

# Phase 1 Plan 01: Docker Compose + Schema Summary

**One-liner:** Four-service Docker Compose stack with PostgreSQL 16 + pgvector HNSW indexes (m=32, ef_construction=128), full schema including unknown_clusters/match_tier/unknown_cluster_id from day 1, and InsightFace buffalo_l baked into the ingestion-worker image at build time.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 01.1 | docker-compose.yml + .env.example + .gitignore | f0ea07b |
| 01.2 | db/init/001_schema.sql — full PostgreSQL schema | 06d5938 |
| 01.3 | Dockerfiles, requirements.txt files, app stubs, ops guide, README | 85ee0eb |

## Schema Verified

Tables created (in dependency order, no FK forward-reference errors):
1. `videos` — with `error_message TEXT` and `status CHECK` constraint
2. `frames` — only frames with detections stored (comment enforces intent)
3. `detections` — YOLO object detection output
4. `known_persons` — enrollment table
5. `person_embeddings` — multi-embedding per person, `normed_embedding vector(512)`
6. `unknown_clusters` — stable UUID PKs, `label TEXT`, `appearance_count INT`
7. `face_detections` — `normed_embedding vector(512)`, `match_tier CHECK ('confident','probable')`, `unknown_cluster_id UUID REFERENCES unknown_clusters(id) ON DELETE SET NULL`

HNSW indexes: `m=32, ef_construction=128` on both `person_embeddings` and `face_detections`.

## HNSW Index Parameters Confirmed

| Index | m | ef_construction | ef_search |
|-------|---|-----------------|-----------|
| person_embeddings_hnsw_idx | 32 | 128 | 64 (postgres command arg) |
| face_detections_hnsw_idx | 32 | 128 | 64 (postgres command arg) |

## Deviations from Plan

### Auto-added: ingestion-worker port mapping

**Rule 2 — Missing critical functionality**  
**Found during:** Task 01.1  
**Issue:** Plan's docker-compose.yml spec did not include `ports:` for the ingestion-worker service, but the plan's `must_haves` requires `GET /health` to return 200 on both `:8001` and `:8000`. Without a port mapping, the ingestion-worker health endpoint is unreachable from the host.  
**Fix:** Added `ports: ["${WORKER_PORT:-8001}:8001"]` to ingestion-worker and `WORKER_PORT=8001` to .env.example.  
**Files modified:** docker-compose.yml, .env.example

### Auto-added: services/web/nginx.conf

**Rule 2 — Missing critical functionality**  
**Found during:** Task 01.3  
**Issue:** The repo layout in the plan spec lists `services/web/nginx.conf` as a required file, and the web Dockerfile references it (`COPY nginx.conf`). The task action only specified the Dockerfile content.  
**Fix:** Created `services/web/nginx.conf` with static file serving, /nginx-health endpoint, and /api/ proxy to the api service.  
**Files created:** services/web/nginx.conf

### Auto-added: ingestion-worker/app/main.py stub

**Rule 3 — Blocking issue**  
**Found during:** Task 01.3  
**Issue:** The ingestion-worker Dockerfile has `COPY app/ ./app/` — the build would fail if the `app/` directory does not exist in the build context.  
**Fix:** Created `services/ingestion-worker/app/main.py` with a minimal FastAPI app serving GET /health, matching the `must_haves` requirement for health on :8001.  
**Files created:** services/ingestion-worker/app/main.py, services/ingestion-worker/app/__init__.py

### Auto-added: ONNX_DISABLE_GLOBAL_THREAD_POOL=1

**Rule 2 — Missing critical functionality (memory safety)**  
**Found during:** Task 01.3  
**Issue:** STACK.md §Flags/Important #2 explicitly calls out setting `ONNX_DISABLE_GLOBAL_THREAD_POOL=1` alongside `OMP_NUM_THREADS=4` to prevent thread oversubscription on the i5-6200.  
**Fix:** Added `ENV ONNX_DISABLE_GLOBAL_THREAD_POOL=1` to ingestion-worker Dockerfile.  
**Files modified:** services/ingestion-worker/Dockerfile

## Self-Check

### Files exist:
- [x] docker-compose.yml ✓
- [x] .env.example ✓
- [x] .gitignore (with .env protected) ✓
- [x] db/init/001_schema.sql ✓
- [x] services/ingestion-worker/Dockerfile (with buffalo_l baking) ✓
- [x] services/ingestion-worker/requirements.txt (insightface==0.7.3, onnxruntime==1.26.0) ✓
- [x] services/ingestion-worker/app/main.py ✓
- [x] services/api/Dockerfile ✓
- [x] services/api/requirements.txt (scikit-learn==1.8.0) ✓
- [x] services/api/app/main.py (GET /health) ✓
- [x] services/web/Dockerfile (nginx:1.27-alpine) ✓
- [x] services/web/nginx.conf ✓
- [x] docs/operations.md (4 GB swap file with fallocate commands) ✓
- [x] README.md ✓

### Commits exist:
- [x] f0ea07b — chore(01-01): docker-compose.yml, .env.example, .gitignore ✓
- [x] 06d5938 — feat(01-02): db/init/001_schema.sql ✓
- [x] 85ee0eb — feat(01-03): service Dockerfiles, requirements, app stubs, ops guide ✓

## Self-Check: PASSED
