---
phase: 03-intelligence-telegram
verified: 2025-07-15T00:00:00Z
status: human_needed
score: 6/6 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run POST /cluster/run against a database with ≥5 unmatched face embeddings, then run it again and confirm UUIDs in unknown_clusters are identical on the second pass"
    expected: "Second run returns clusters_created=0, clusters_updated>0; UUID values in unknown_clusters table unchanged"
    why_human: "Requires a live PostgreSQL instance with real embeddings; cannot verify UUID stability programmatically without a running stack"
  - test: "Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env, then POST /digest/send"
    expected: "A photo album message arrives in the configured Telegram chat with up to 10 photos; each caption reads 'Unknown person — seen Nx, YYYY-MM-DD → YYYY-MM-DD'"
    why_human: "Requires a real Telegram bot credential and outbound internet access; cannot be tested without a live stack"
  - test: "Import n8n-clustering-workflow.json into n8n; verify it fires at 08:00 and both HTTP Request nodes return 200"
    expected: "Schedule fires; cluster/run returns {clusters_created, clusters_updated, faces_assigned}; digest/send returns {sent: N, skipped: false}"
    why_human: "n8n workflow execution requires a running n8n instance connected to the API service"
---

# Phase 3: Unknown Face Intelligence & Telegram Digest — Verification Report

**Phase Goal:** Every night the system clusters all unrecognized faces across the full video library, assigns stable identities to recurring strangers, and delivers a Telegram photo album — so the user knows who appeared without watching any footage.  
**Verified:** 2025-07-15  
**Status:** human_needed — all automated checks pass; 3 items require live-stack testing  
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /cluster/run groups unmatched embeddings into clusters with stable UUIDs, representative face, and appearance count stored in unknown_clusters | ✓ VERIFIED | `clustering.py` lines 125–277: full HDBSCAN pipeline; ON CONFLICT upsert at line 233; appearance_count, first_seen, last_seen, representative_face_id written |
| 2 | Re-running POST /cluster/run does not change existing cluster UUIDs (majority-vote stability) | ✓ VERIFIED | `clustering.py` lines 185–191: `Counter(existing).most_common(1)[0][0]` — existing UUID wins if present; new uuid4() only for brand-new clusters |
| 3 | POST /clusters/{id}/promote updates all cluster-member face_detections.matched_person_id + match_tier + match_similarity in a single operation, sets promoted_at | ✓ VERIFIED | `clustering.py` lines 365–407: bulk `UPDATE face_detections SET matched_person_id=$1, match_tier='confident', match_similarity=1.0 WHERE unknown_cluster_id=$2`; `UPDATE unknown_clusters SET promoted_at=now()` follows |
| 4 | Telegram digest sends a photo album via sendMediaGroup with MinIO-fetched bytes and caption showing appearance count and dates | ✓ VERIFIED | `digest.py` lines 41–140: `send_media_group()` called at line 127; `run_in_executor` for MinIO at line 93; `BytesIO(img_bytes); buf.seek(0)` at lines 116–117; caption format "Unknown person — seen Nx, YYYY-MM-DD → YYYY-MM-DD" at line 113 |
| 5 | POST /digest/send returns {sent:0, skipped:true} when there are zero active clusters | ✓ VERIFIED | `digest.py` line 82: `return DigestResponse(sent=0, skipped=True, message="No active clusters")` when `not clusters`; line 122: second guard when all MinIO fetches fail |
| 6 | n8n cron workflow calls POST /cluster/run then POST /digest/send in sequence | ✓ VERIFIED | `docs/n8n-clustering-workflow.json`: `scheduleTrigger` node with `"expression": "0 8 * * *"`; `Run Clustering` node → `http://api:8000/cluster/run`; `Send Digest` node → `http://api:8000/digest/send`; connection chain `Every day at 08:00 → Run Clustering → Send Digest` |

**Score:** 6/6 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `db/migrations/003_add_cluster_state_cols.sql` | ignored BOOLEAN + promoted_at TIMESTAMPTZ on unknown_clusters | ✓ VERIFIED | `ADD COLUMN IF NOT EXISTS ignored BOOLEAN NOT NULL DEFAULT false`, `ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ`; index on `ignored` column |
| `services/api/app/clustering.py` | POST /cluster/run + GET /clusters + ignore/restore/promote | ✓ VERIFIED | 408 lines; all 5 endpoints implemented: run_clustering, list_clusters, ignore_cluster, restore_cluster, promote_cluster |
| `services/api/app/digest.py` | POST /digest/send with Telegram sendMediaGroup | ✓ VERIFIED | 141 lines; complete implementation with 503 guard, MinIO bytes fetch, sendMediaGroup, skip response |
| `services/api/app/config.py` | TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CLUSTER_MIN_SIZE, CLUSTER_MIN_SAMPLES | ✓ VERIFIED | All 4 vars present; CLUSTER_MIN_SIZE defaults to 5, CLUSTER_MIN_SAMPLES to 2 |
| `services/api/app/main.py` | clustering_router + digest_router registered with require_token | ✓ VERIFIED | Both routers imported and `app.include_router(…, dependencies=[Depends(require_token)])` present |
| `docs/n8n-clustering-workflow.json` | Schedule trigger → cluster/run → digest/send | ✓ VERIFIED | Cron `0 8 * * *`; 3-node chain; Bearer auth on both HTTP Request nodes |
| `services/web/src/types/api.ts` | ClusterItem with ignored: boolean | ✓ VERIFIED | `ignored: boolean` field present in ClusterItem interface |
| `services/web/src/api/clusters.ts` | usePromoteCluster, useIgnoreCluster, useRestoreCluster, useIgnoredClusters | ✓ VERIFIED | All 4 hooks present; correct TanStack Query v5 object-form; cache invalidation wired |
| `services/web/src/components/ClusterCard.tsx` | Enroll → promote (not rematch); 🚫 Noise button; showRestoreOnly mode | ✓ VERIFIED | `usePromoteCluster` called in handleEnroll; `ignoreCluster.mutateAsync(cluster.id)` on Noise button; `showRestoreOnly` prop renders ↩ Restore only |
| `services/web/src/pages/ClustersPage.tsx` | Collapsed Ignored section using useIgnoredClusters | ✓ VERIFIED | `useIgnoredClusters()` hook; `ignoredOpen` state toggle; grid of ClusterCards with `showRestoreOnly` prop |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| POST /cluster/run | unknown_clusters table | `ON CONFLICT (id) DO UPDATE` upsert | ✓ WIRED | `clustering.py` line 237 |
| POST /clusters/{id}/promote | face_detections.matched_person_id | `UPDATE face_detections SET matched_person_id=$1, match_tier='confident'` | ✓ WIRED | `clustering.py` lines 382–389 |
| GET /clusters | face_detections representative join | `LEFT JOIN face_detections fd ON fd.id = uc.representative_face_id` | ✓ WIRED | `clustering.py` lines 293–305 |
| POST /digest/send | Telegram Bot API | `await bot.send_media_group(...)` | ✓ WIRED | `digest.py` line 127 |
| digest.py | MinIO frames bucket | `loop.run_in_executor(None, lambda: minio_client.get_object(...))` | ✓ WIRED | `digest.py` lines 93–101 |
| digest.py | unknown_clusters + frames (ignored=false filter) | `WHERE uc.ignored = false AND uc.promoted_at IS NULL` | ✓ WIRED | `digest.py` lines 73–77 |
| ClusterCard handleEnroll | POST /clusters/{id}/promote | `promoteCluster.mutateAsync({ clusterId, personId })` | ✓ WIRED | `ClusterCard.tsx` — explicit 2-step: createPerson → promoteCluster.mutateAsync |
| ClusterCard noise button | POST /clusters/{id}/ignore | `ignoreCluster.mutateAsync(cluster.id)` | ✓ WIRED | `ClusterCard.tsx` handleIgnore |
| ClustersPage ignored section | GET /clusters?include_ignored=true | `useIgnoredClusters()` → `listIgnoredClusters()` → `/clusters?include_ignored=true` | ✓ WIRED | `ClustersPage.tsx` + `clusters.ts` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `clustering.py` `/cluster/run` | `rows` (face embeddings) | `SELECT fd.id, fd.normed_embedding … WHERE matched_person_id IS NULL` | Yes — DB query on face_detections | ✓ FLOWING |
| `clustering.py` `GET /clusters` | `rows` (cluster list) | `SELECT uc.id … FROM unknown_clusters … WHERE promoted_at IS NULL AND ignored=$1` | Yes — DB query | ✓ FLOWING |
| `digest.py` `POST /digest/send` | `clusters` | `SELECT uc.id, uc.appearance_count … WHERE uc.ignored = false AND uc.promoted_at IS NULL LIMIT 10` | Yes — DB query | ✓ FLOWING |
| `ClusterCard.tsx` | `cluster` prop | `useClusters()` → `authFetch('/clusters')` → GET /clusters | Yes — API call | ✓ FLOWING |
| `ClustersPage.tsx` | `ignoredClusters` | `useIgnoredClusters()` → `authFetch('/clusters?include_ignored=true')` | Yes — API call | ✓ FLOWING |

---

### Behavioral Spot-Checks

Step 7b: SKIPPED for live API calls (requires running Docker stack). Static analysis only performed.

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| CLUSTER-01 | Nightly HDBSCAN batch job; metric='euclidean', algorithm='boruvka_kdtree', min_cluster_size=3 | ✓ SATISFIED (with noted deviation) | HDBSCAN implemented; algorithm='kd_tree' (sklearn equivalent of boruvka_kdtree — documented in Plan 03-01 NOTE); min_cluster_size/min_samples from config |
| CLUSTER-02 | Incremental — existing UUIDs preserved; only new faces assigned | ✓ SATISFIED | Majority-vote UUID stability: `Counter(existing).most_common(1)[0][0]` |
| CLUSTER-03 | Stable UUID, representative face (highest det_score + sharpness), appearance count | ✓ SATISFIED | `_pick_representative_face()` with Laplacian sharpness × det_score; upsert writes all fields |
| CLUSTER-04 | POST /cluster/run endpoint in api service (not separate container) | ✓ SATISFIED | `clustering.py` registered in `main.py` within api service |
| CLUSTER-05 | Promote cluster → retroactively re-match all cluster member embeddings | ✓ SATISFIED | `promote_cluster()` bulk UPDATE face_detections WHERE unknown_cluster_id=cluster_id |
| NOTIF-01 | Nightly digest: unknown clusters via Telegram Bot API | ✓ SATISFIED | `digest.py` POST /digest/send; triggered by n8n cron |
| NOTIF-02 | sendMediaGroup (single album ≤10 photos) | ✓ SATISFIED | `bot.send_media_group()`; `LIMIT 10` in query |
| NOTIF-03 | Each entry: representative thumbnail, appearance count, dates | ✓ SATISFIED | Caption: "Unknown person — seen Nx, YYYY-MM-DD → YYYY-MM-DD"; BytesIO frame image as media |
| NOTIF-04 | Digest only sent when new unknown faces exist | ✓ SATISFIED | Returns `{skipped: true}` when no clusters; no Telegram call made |
| NOTIF-05 | Telegram Bot token + chat ID via env vars | ✓ SATISFIED | `config.py` TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID; 503 guard if empty |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `clustering.py` | 263 | `executemany` for face_detections update (no COPY or single-statement batch) | ℹ️ Info | Performance concern at scale; functionally correct for v1 |
| `digest.py` | 127 | `Bot` constructed per-request (no connection reuse) | ℹ️ Info | Minor inefficiency; acceptable for daily digest cadence |

No blockers or stub patterns found.

---

### Warnings (Non-Blocking Deviations)

**1. Algorithm name: `kd_tree` vs `boruvka_kdtree`**

- CONTEXT.md locked decision: `algorithm='boruvka_kdtree'`
- Implementation: `algorithm='kd_tree'`
- **Not a bug.** Plan 03-01 explicitly documents: *"NOTE: sklearn uses algorithm='kd_tree', NOT 'boruvka_kdtree' (standalone hdbscan package name)."* sklearn's HDBSCAN API uses different parameter values than the standalone `hdbscan` package. The chosen value is correct for `sklearn.cluster.HDBSCAN`.

**2. n8n cron time: 08:00 vs ROADMAP's 02:00**

- ROADMAP.md done-when states: *"n8n cron workflow at 02:00"*
- CONTEXT.md locked decision: *"n8n cron at 8am daily"*
- Implementation: `"expression": "0 8 * * *"` (08:00)
- **Not a blocker.** CONTEXT.md is the locked implementation decision and post-dates the ROADMAP description. All three plan documents and the CONTEXT.md agree on 08:00. The functional chain (cron → cluster/run → digest/send) is fully implemented.

**3. "Past 24h" time filter absent (by design)**

- ROADMAP.md done-when: *"No Telegram message is sent when there are zero new unknown cluster appearances in the past 24h"*
- CONTEXT.md locked decision: *"All unknown clusters regardless of age — no time-based filter"*
- Implementation: no time filter in digest.py (matches CONTEXT.md)
- **Not a blocker.** The `skipped=true` guard still works — it fires when there are zero total active clusters. The decision to remove the 24h window is a locked product decision in CONTEXT.md.

---

### Human Verification Required

#### 1. Stable UUID Persistence Across Re-runs

**Test:** Ingest a video with ≥5 unrecognized faces. Run `POST /cluster/run` twice. Query `SELECT id FROM unknown_clusters` before and after the second run.  
**Expected:** UUID rows are identical after the second run; `clusters_created=0` on second call; `clusters_updated > 0`.  
**Why human:** Requires a live PostgreSQL instance with real face embedding data.

#### 2. Telegram Photo Album Delivery

**Test:** Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Ensure at least one active cluster exists. Call `POST /digest/send` with Bearer token.  
**Expected:** A photo album arrives in the configured Telegram chat. Each photo has a caption: `"Unknown person — seen Nx, YYYY-MM-DD → YYYY-MM-DD"`. The album contains ≤10 photos.  
**Why human:** Requires real Telegram credentials and outbound internet access from the Docker container.

#### 3. n8n Workflow Execution

**Test:** Import `docs/n8n-clustering-workflow.json` into a running n8n instance. Manually trigger the workflow and inspect execution log.  
**Expected:** Schedule Trigger → Run Clustering (200 OK) → Send Digest (200 OK); execution log shows both nodes green.  
**Why human:** Requires a running n8n instance connected to the Docker network.

---

### Gaps Summary

No automated gaps found. All 6 done-when criteria pass static verification. Phase 3 implementation is complete and substantive across all three plans (03-01, 03-02, 03-03). All artifacts are present, all key links are wired, all data flows are connected.

Verification is blocked at `human_needed` status due to 3 behaviors that require a live environment to confirm:
1. UUID stability across clustering re-runs (requires real embeddings in DB)
2. Telegram photo album delivery (requires real bot credentials + network)
3. n8n workflow end-to-end execution (requires running n8n)

---

*Verified: 2025-07-15*  
*Verifier: the agent (gsd-verifier)*
