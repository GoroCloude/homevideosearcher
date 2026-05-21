---
phase: 03-intelligence-telegram
plan: "02"
subsystem: api-digest-telegram
tags: [telegram, digest, python-telegram-bot, minio, asyncpg, n8n, fastapi]
dependency_graph:
  requires:
    - "03-01 — clustering engine (unknown_clusters table with ignored/promoted_at columns)"
    - "02-*/02-01 — asyncpg pool, auth pattern"
    - "01-*/01-01 — face_detections schema (representative_face_id, minio_key)"
  provides:
    - "POST /digest/send — Telegram photo album with unknown cluster thumbnails"
    - "docs/n8n-clustering-workflow.json — importable n8n workflow for daily automation"
  affects:
    - "services/api/app/main.py — digest_router registered after clustering_router"
tech_stack:
  added:
    - "python-telegram-bot v22 async API — Bot(token=...) + await bot.send_media_group()"
    - "asyncio.get_running_loop().run_in_executor — wraps synchronous minio.get_object()"
    - "io.BytesIO + seek(0) — required for InputMediaPhoto to read from start of buffer"
    - "n8n scheduleTrigger (0 8 * * *) — daily 8am cron triggering cluster/run then digest/send"
  patterns:
    - "run_in_executor(None, lambda key=minio_key: ...) — closure captures loop variable correctly"
    - "503 guard on empty TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — feature-flag for disabled state"
    - "continue-on-MinIO-error per cluster — partial digest still sends even if some frames missing"
key_files:
  created:
    - services/api/app/digest.py
    - docs/n8n-clustering-workflow.json
  modified:
    - services/api/app/main.py
decisions:
  - "Caption format uses Unicode em-dash (U+2014) and multiplication sign (U+00D7): 'Unknown person — seen N×, YYYY-MM-DD → YYYY-MM-DD'"
  - "lambda key=minio_key captures loop variable by value — avoids closure bug where all lambdas would use last loop value"
  - "Per-cluster error handling with continue: partial digest (some frames unfetchable) still sends rather than failing entirely"
  - "n8n API_TOKEN via $env.API_TOKEN — token stored in n8n env vars, not hardcoded in workflow JSON"
  - "T-03-07: TELEGRAM_BOT_TOKEN never logged — only used as boolean check and passed to Bot() constructor"
metrics:
  duration: "~15 minutes"
  completed_date: "2025-07"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 1
---

# Phase 3 Plan 02: Telegram Digest Endpoint — Summary

**One-liner:** Telegram daily digest endpoint fetches unknown cluster thumbnails from MinIO via thread executor, builds BytesIO with seek(0), and sends a photo album via python-telegram-bot v22 async sendMediaGroup; n8n workflow chains daily 8am cron → cluster/run → digest/send.

---

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | digest.py POST /digest/send + main.py wiring | 3da3dac | services/api/app/digest.py, services/api/app/main.py |
| 2 | n8n clustering workflow JSON | 8398c6c | docs/n8n-clustering-workflow.json |

---

## What Was Built

### `services/api/app/digest.py`

**`POST /digest/send`** — Telegram digest sender:

1. **503 guard**: Returns HTTP 503 immediately if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are empty strings (feature is disabled by default).
2. **DB query**: Fetches up to 10 active unknown clusters (non-ignored, non-promoted) with representative frame `minio_key` via LEFT JOIN chain `unknown_clusters → face_detections → frames`.
3. **Early return**: Returns `{sent: 0, skipped: true}` if no clusters found.
4. **MinIO fetch**: For each cluster, fetches frame bytes via `asyncio.get_running_loop().run_in_executor()` — wraps synchronous `minio_client.get_object()` in a thread pool. Lambda captures `minio_key` by value to avoid closure bug.
5. **Error isolation**: Individual MinIO failures log a warning and `continue` — remaining clusters still send.
6. **BytesIO preparation**: Calls `buf.seek(0)` before passing to `InputMediaPhoto` — required or Telegram send fails silently.
7. **Caption format**: `f"Unknown person — seen {count}×, {first} → {last}"` (Unicode em-dash + multiplication sign + arrow).
8. **Telegram send**: Uses `Bot(token=config.TELEGRAM_BOT_TOKEN)` + `await bot.send_media_group(chat_id=..., media=[...])`. Wraps in try/except for `TelegramError` → HTTP 502.
9. **Success**: Returns `{sent: N, skipped: false}`.

### `docs/n8n-clustering-workflow.json`

Importable n8n workflow with 3 nodes:
- **Schedule Trigger**: Cron `0 8 * * *` (daily at 08:00)
- **Run Clustering**: POST `http://api:8000/cluster/run` — Authorization Bearer `{{ $env.API_TOKEN }}`, 5-minute timeout (300000ms)
- **Send Digest**: POST `http://api:8000/digest/send` — Authorization Bearer `{{ $env.API_TOKEN }}`, 60-second timeout (60000ms)
- Sequential connection: scheduleTrigger → Run Clustering → Send Digest

### `services/api/app/main.py`

Appended two lines after `clustering_router` registration:
```python
from .digest import router as digest_router
app.include_router(digest_router, dependencies=[Depends(require_token)])
```

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Threat Model Compliance

All T-03-06 through T-03-10 dispositions applied:
- **T-03-06 (Spoofing):** `digest_router` registered with `dependencies=[Depends(require_token)]`
- **T-03-07 (Info Disclosure):** `TELEGRAM_BOT_TOKEN` never logged; only used as boolean check and passed to `Bot()` constructor
- **T-03-08 (DoS):** `LIMIT 10` in SQL; each `get_object` bounded by frame file size
- **T-03-09 (Info Disclosure):** `TelegramError` messages (from library) contain no secrets; acceptable for self-hosted setup
- **T-03-10 (Tampering):** n8n `API_TOKEN` stored as n8n environment variable, not hardcoded in workflow JSON

---

## Known Stubs

None — endpoint is fully wired. Telegram credentials default to empty string (503 response), which is the correct disabled-by-default behavior documented in `CONTEXT.md`.

---

## Self-Check: PASSED

Files created/modified:
- ✅ services/api/app/digest.py (created)
- ✅ docs/n8n-clustering-workflow.json (created)
- ✅ services/api/app/main.py (modified — digest_router appended)

Commits exist:
- ✅ 3da3dac feat(03-02): digest.py POST /digest/send + register digest_router in main.py
- ✅ 8398c6c feat(03-02): n8n clustering & digest daily workflow JSON
