---
phase: 03-intelligence-telegram
plan: "01"
subsystem: api-clustering
tags: [hdbscan, clustering, fastapi, asyncpg, minio, postgresql, migration]
dependency_graph:
  requires:
    - "02-*/02-01 — persons/enrollment API (asyncpg pool, auth pattern)"
    - "01-*/01-01 — face_detections schema (normed_embedding, unknown_cluster_id)"
  provides:
    - "POST /cluster/run — HDBSCAN clustering engine with stable UUIDs"
    - "GET /clusters — list active/ignored clusters with representative frame"
    - "POST /clusters/{id}/ignore — mark cluster as noise"
    - "DELETE /clusters/{id}/ignore — restore cluster"
    - "POST /clusters/{id}/promote — bulk-assign cluster to known person"
  affects:
    - "services/api/app/main.py — clustering_router registered"
    - "unknown_clusters table — added ignored + promoted_at columns"
    - "face_detections.unknown_cluster_id — cleared and re-assigned on each run"
tech_stack:
  added:
    - "sklearn.cluster.HDBSCAN (scikit-learn) — algorithm='kd_tree', metric='euclidean'"
    - "cv2.Laplacian — sharpness scoring for representative face selection"
    - "asyncio.get_running_loop().run_in_executor — wraps synchronous minio.get_object()"
    - "collections.Counter — majority-vote stable UUID strategy"
  patterns:
    - "asyncpg ON CONFLICT (id) DO UPDATE for idempotent cluster upsert"
    - "asyncpg executemany for bulk face_detections update"
    - "FastAPI APIRouter without prefix (routes defined with full paths)"
key_files:
  created:
    - db/migrations/003_add_cluster_state_cols.sql
    - services/api/app/clustering.py
  modified:
    - services/api/app/config.py
    - services/api/app/main.py
    - .env.example
decisions:
  - "algorithm='kd_tree' not 'boruvka_kdtree' — sklearn uses different parameter name than standalone hdbscan package"
  - "Stable UUID strategy: majority vote of existing unknown_cluster_id among cluster members; new uuid4() if none exist"
  - "GET /clusters?include_ignored=true returns ONLY ignored clusters (not all+ignored); uses AND uc.ignored = $1"
  - "Representative face: top 3 by det_score, pick best det_score × min(sharpness/100, 1.0) combined score"
  - "Step 6 clears unknown_cluster_id = NULL for all unmatched faces before re-assigning (clean re-run)"
  - "CLUSTER_MIN_SIZE default = 5 (locked in CONTEXT.md, fixed from .env.example=3)"
  - "clustering.py uses router = APIRouter(tags=['clustering']) with no prefix — routes define full paths"
metrics:
  duration: "~20 minutes"
  completed_date: "2025-07"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 3
---

# Phase 3 Plan 01: Clustering Engine — Summary

**One-liner:** HDBSCAN clustering engine with stable UUID majority-vote, Laplacian sharpness representative selection, and 5 cluster management REST endpoints registered under bearer-token auth.

---

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | DB migration + config/env setup | 962360d | db/migrations/003_add_cluster_state_cols.sql, config.py, .env.example |
| 2 | clustering.py — HDBSCAN engine + all endpoints | 68bc958 | services/api/app/clustering.py |
| 3 | main.py router wiring | 495e75d | services/api/app/main.py |

---

## What Was Built

### DB Migration (`003_add_cluster_state_cols.sql`)
Adds two columns to `unknown_clusters`:
- `ignored BOOLEAN NOT NULL DEFAULT false` — soft-delete for noise clusters
- `promoted_at TIMESTAMPTZ` — set when cluster is enrolled as known person; filters out of `GET /clusters`
- Index on `ignored` for efficient filtering

### Config (`config.py`, `.env.example`)
Four new env vars:
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — empty strings = digest disabled (used in Plan 03-03)
- `CLUSTER_MIN_SIZE=5` / `CLUSTER_MIN_SAMPLES=2` — HDBSCAN parameters

### Clustering Engine (`clustering.py`)
**`POST /cluster/run`** — Idempotent HDBSCAN clustering:
1. Loads all `face_detections` where `matched_person_id IS NULL AND normed_embedding IS NOT NULL`
2. Returns early if count < `CLUSTER_MIN_SIZE`
3. Runs `sklearn.cluster.HDBSCAN(algorithm='kd_tree', metric='euclidean', n_jobs=1)`
4. Assigns stable UUIDs via majority-vote of existing `unknown_cluster_id` values (Counter)
5. Picks representative face: top 3 by `det_score`, scores each by `det_score × min(Laplacian_var/100, 1.0)` using async MinIO fetch in `run_in_executor`
6. UPSERTs `unknown_clusters` rows with `ON CONFLICT (id) DO UPDATE`
7. Clears all `unknown_cluster_id = NULL` for unmatched faces, then bulk-assigns via `executemany`

**`GET /clusters`** — Returns clusters where `promoted_at IS NULL AND ignored = $1`:
- Default (`include_ignored=False`): active clusters only
- `?include_ignored=true`: ignored clusters only (for UI collapsed section)
- JOINs `face_detections → frames` to resolve `representative_frame_id`
- Constructs `thumbnail_url = /frames/{frame_id}/image`

**`POST /clusters/{id}/ignore`** — Sets `ignored=true`; 404 on `UPDATE 0`

**`DELETE /clusters/{id}/ignore`** — Sets `ignored=false`; 404 on `UPDATE 0`

**`POST /clusters/{id}/promote?person_id={uuid}`**:
- Verifies cluster exists (404 if not)
- Bulk-updates `face_detections SET matched_person_id=$1, match_tier='confident', match_similarity=1.0 WHERE unknown_cluster_id=$2 AND matched_person_id IS NULL`
- Sets `promoted_at=now()` on cluster row

### main.py
`clustering_router` registered after `frames_router` with `dependencies=[Depends(require_token)]`.

---

## Deviations from Plan

### Minor: Full clustering.py written in single commit (Tasks 2+3 combined for the file)

- **Found during:** Task 2 execution
- **Issue:** Plan split clustering.py creation (Task 2 = engine only) and endpoint appending (Task 3 = management endpoints) into two steps. Since the file didn't exist yet, writing the complete file in one shot is equivalent and cleaner.
- **Fix:** Created complete clustering.py in Task 2's commit; Task 3 commit covers only main.py changes.
- **Impact:** Zero — end state identical to plan specification.

---

## Threat Model Compliance

All T-03-01 through T-03-05 mitigations applied:
- **T-03-01 (Spoofing):** `clustering_router` registered with `dependencies=[Depends(require_token)]`
- **T-03-03 (Injection):** All SQL uses asyncpg parameterized `$1`/`$2` placeholders
- **T-03-04 (Info Disclosure):** Errors surface as `HTTPException` with generic messages only
- **T-03-05 (EoP):** promote endpoint guards with `AND matched_person_id IS NULL`; `person_id` validated as UUID by FastAPI

---

## Known Stubs

None — all endpoints are fully wired. `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` vars are empty-string defaults (digest disabled until Plan 03-03 implements the digest endpoint).

---

## Self-Check: PASSED

Files created/modified:
- ✅ db/migrations/003_add_cluster_state_cols.sql
- ✅ services/api/app/clustering.py
- ✅ services/api/app/config.py
- ✅ services/api/app/main.py
- ✅ .env.example

Commits exist:
- ✅ 962360d feat(03-01): DB migration + config/env setup
- ✅ 68bc958 feat(03-01): clustering.py — HDBSCAN engine + all cluster management endpoints
- ✅ 495e75d feat(03-01): register clustering_router in main.py
