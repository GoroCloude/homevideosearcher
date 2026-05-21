# Phase 3 — Intelligence + Telegram: CONTEXT.md

**Phase:** 03-intelligence-telegram  
**Status:** Discussed — ready for research + planning  
**Date:** 2025-07

---

## What Phase 3 delivers

1. **HDBSCAN clustering** — group all unrecognized face embeddings into stable "unknown clusters" via `POST /cluster/run`; expose via `GET /clusters`
2. **Cluster management** — mark clusters as ignored (`POST /clusters/{id}/ignore`), restore them, promote clusters to named persons (`POST /clusters/{id}/promote`)
3. **Telegram digest** — `POST /digest/send` sends unknown cluster thumbnails + stats via Telegram `sendMediaGroup`; n8n cron calls it daily at 8am

---

## Locked decisions

### Telegram

| Decision | Value |
|---|---|
| Credentials | User already has `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; add to `.env` and `config.py` |
| Message format | `sendMediaGroup` — up to 10 photos, each captioned with appearance count + first/last seen dates |
| Trigger | `POST /digest/send` endpoint (manual) + n8n cron at 8am daily using HTTP Request node with `Authorization: Bearer <API_TOKEN>` header |
| Time filter | **All unknown clusters** regardless of age — no time-based filter |
| Max photos per digest | 10 (Telegram sendMediaGroup limit) |

### HDBSCAN clustering

| Decision | Value |
|---|---|
| `min_cluster_size` | **5** |
| `min_samples` | **2** |
| `metric` | `euclidean` |
| Algorithm | `boruvka_kdtree` (as in ROADMAP) |
| Input | All `face_detections` where `matched_person_id IS NULL` |
| Incremental | Stable UUIDs — re-run merges new noise faces into existing clusters; doesn't recreate from scratch |
| Representative face | Highest `det_score` + sharpest image (Variance of Laplacian) |

### Cluster management UI/API

| Decision | Value |
|---|---|
| `GET /clusters` filter | Only unenrolled + non-ignored clusters (promoted/enrolled clusters disappear from list) |
| Mark as noise | `POST /clusters/{id}/ignore` — sets `ignored=true` in DB (does NOT delete) |
| Restore noise | `DELETE /clusters/{id}/ignore` — sets `ignored=false`; ignored clusters shown in collapsed section in UI |
| UI — ignored section | Collapsed "Ignored" section on ClustersPage showing ignored clusters with Restore button |
| Cluster promotion | Dedicated `POST /clusters/{id}/promote?person_id={pid}` — bulk `UPDATE face_detections SET matched_person_id=pid WHERE unknown_cluster_id=cluster_id`; ClusterCard.tsx must be updated to call this endpoint (NOT the current create+rematch flow which doesn't handle cluster membership) |

---

## What the planner must NOT change

- The `ClusterItem` TypeScript type already defined in `api.ts` — planner uses it as-is or extends it
- Existing `ClusterCard.tsx` enrollment form (the name input + OK button) — but the **submit action** must change from `createPerson+rematch` to `createPerson → POST /clusters/{id}/promote`
- `unknown_clusters` table — already exists in DB schema from Phase 1
- `face_detections.unknown_cluster_id` FK — already exists
- `GET /clusters` route path — frontend already calls `/clusters`

---

## Implementation scope

### Plan 1: Clustering engine (`POST /cluster/run` + `GET /clusters`)
- New `clustering.py` module in `services/api/app/` with HDBSCAN logic
- Load all null-person embeddings from `face_detections`
- Run HDBSCAN, generate stable UUIDs (hash of sorted member face_detection IDs)
- Write to `unknown_clusters`, update `face_detections.unknown_cluster_id`
- Representative: `SELECT id, det_score FROM face_detections WHERE cluster=x ORDER BY det_score DESC LIMIT 1` then blur check
- `POST /cluster/run` — protected endpoint (requires API token)
- `GET /clusters` — returns active (not ignored, not promoted) clusters

### Plan 2: Cluster management endpoints
- `POST /clusters/{id}/ignore` — set `ignored=true`
- `DELETE /clusters/{id}/ignore` — set `ignored=false`
- `POST /clusters/{id}/promote` — accepts `person_id` query param, bulk UPDATE
- `GET /clusters?include_ignored=true` — for the collapsed section
- Update `ClusterCard.tsx` to call `POST /clusters/{id}/promote` after `createPerson`
- Add collapsed "Ignored" section to `ClustersPage.tsx`

### Plan 3: Telegram digest (`POST /digest/send`)
- New `digest.py` module in `services/api/app/`
- Query all non-ignored, non-promoted clusters
- For each cluster: fetch representative frame thumbnail from MinIO
- Send via Telegram Bot API `sendMediaGroup` (up to 10 photos)
- Caption format: `"Unknown person — seen Nx, {first_seen} → {last_seen}"`
- n8n workflow: Cron trigger at 8am → HTTP Request to `POST /digest/send` with Bearer token
- Env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

---

## Deferred ideas

- None noted during discussion

---

## Canonical refs

- `.planning/ROADMAP.md` — Phase 3 requirements (CLUSTER-01–05, NOTIF-01–05)
- `.planning/REQUIREMENTS.md` — full requirements list
- `services/api/app/persons.py` — enrollment patterns to reuse
- `services/web/src/components/ClusterCard.tsx` — enrollment UI (needs modification)
- `services/web/src/pages/ClustersPage.tsx` — clusters page (needs ignored section)
- `services/web/src/api/clusters.ts` — existing `GET /clusters` hook
- `services/web/src/types/api.ts` — `ClusterItem` type
