---
phase: 10-watch-folder-auto-ingest
plan: "02"
subsystem: watcher
tags: [watchdog, minio, httpx, tdd, polling, rsync, deduplication]
dependency_graph:
  requires: [10-01]
  provides: [watcher-service, video-auto-ingest, startup-scan-dedup]
  affects:
    - services/watcher/
    - services/ingestion-worker/app/main.py
tech_stack:
  added:
    - watchdog>=4.0 (inotify + polling filesystem observer)
    - minio==7.2.20 (MinIO Python SDK)
    - httpx>=0.27 (async HTTP client for /ingest POST)
  patterns:
    - asyncio.run_coroutine_threadsafe (sync watchdog thread → async event loop bridge)
    - asyncio.to_thread (blocking fput_object → thread pool)
    - mtime-based MinIO key determinism (startup_scan restart deduplication)
    - on_closed() NOT on_created() (prevents partial-write uploads)
    - on_moved() for rsync atomic-rename pattern
    - PollingObserver / Observer selection via WATCH_USE_POLLING env var
key_files:
  created:
    - services/watcher/Dockerfile
    - services/watcher/requirements.txt
    - services/watcher/requirements-dev.txt
    - services/watcher/pytest.ini
    - services/watcher/app/__init__.py
    - services/watcher/app/config.py
    - services/watcher/app/storage.py
    - services/watcher/app/watcher.py
    - services/watcher/app/main.py
    - services/watcher/tests/__init__.py
    - services/watcher/tests/conftest.py
    - services/watcher/tests/test_extension_filter.py
    - services/watcher/tests/test_minio_key_scheme.py
  modified:
    - services/ingestion-worker/app/main.py
decisions:
  - "Use on_closed() NOT on_created() — on_created fires while file is still being written; on_closed fires only after write handle released (prevents partial-file uploads)"
  - "mtime-based MinIO key (videos/{file_mtime_ts}_{filename}) for startup_scan — produces stable, deterministic key across watcher restarts; ingestion worker deduplicates by minio_key returning status=skipped"
  - "asyncio.run_coroutine_threadsafe bridges sync watchdog Observer thread to async main event loop — required because watchdog callbacks are not async"
  - "on_moved() handles rsync atomic-rename pattern — rsync writes .tmpXXXXXX then renames to final name; dest_path is the video file"
  - "startup_scan called BEFORE observer.start() — processes files dropped during container downtime before live monitoring begins"
metrics:
  duration: "~20 minutes"
  completed: "2025-01-28"
  tasks_completed: 3
  tasks_total: 3
  files_created: 13
  files_modified: 1
---

# Phase 10 Plan 02: Watch-Folder Auto-Ingest Watcher Service Summary

**One-liner:** Complete `services/watcher/` package using watchdog `on_closed()`+`on_moved()` with mtime-based MinIO key deduplication, asyncio bridge, PollingObserver support, and startup scan for downtime-dropped files.

## What Was Built

Created the complete `services/watcher/` Python service from scratch — a watchdog-based daemon that monitors a local directory and auto-ingests video files into the pipeline.

### Key Design Decisions

**`on_closed()` not `on_created()`** — Watchdog `on_created()` fires when the OS creates the file inode, which happens before the write is complete. For large videos (e.g., a 2 GB holiday recording being copied over SMB), using `on_created()` would upload a partial file. `on_closed()` fires only after the last write handle to the file is released, guaranteeing the file is complete. Requires watchdog >= 4.0.

**mtime-based MinIO keys for deduplication** — The startup scan (run on every container restart) calls `process_file(str(f), mtime=f.stat().st_mtime)`. The mtime is used to derive the MinIO key timestamp: `videos/{YYYYMMDD_HHMMSS}_{filename}`. Because the key is deterministic for a given file (same mtime → same key), the ingestion worker's `SELECT WHERE minio_key = $1` deduplication returns `status='skipped'` for already-processed files on restart, preventing duplicate video DB records.

**`asyncio.run_coroutine_threadsafe` bridge** — Watchdog's Observer runs in a background OS thread. Submitting async coroutines from that thread requires `asyncio.run_coroutine_threadsafe(coro, loop)` with the running event loop passed to `VideoHandler.__init__`. Using `asyncio.create_task()` directly would raise `RuntimeError: no running event loop`.

**rsync atomic-rename via `on_moved()`** — rsync writes to `.fileXXXXXX` temp files then renames to the final path. The rename triggers `on_moved` with `event.dest_path` = the final video filename. Processing `dest_path` (not `src_path`) handles this pattern correctly.

### File Structure

```
services/watcher/
├── Dockerfile                    # python:3.11-slim-bookworm + uv==0.11.14
├── requirements.txt              # watchdog>=4.0, minio==7.2.20, httpx>=0.27
├── requirements-dev.txt          # pytest>=7.4, pytest-asyncio>=0.21
├── pytest.ini                    # testpaths=tests, pythonpath=., asyncio_mode=auto
├── app/
│   ├── __init__.py               # empty package marker
│   ├── config.py                 # all env vars (MINIO_*, WATCH_DIR, WORKER_URL, etc.)
│   ├── storage.py                # MinIO singleton + ensure_bucket + upload_video
│   ├── watcher.py                # _is_video_file, _make_minio_key, process_file,
│   │                             # startup_scan, VideoHandler
│   └── main.py                   # async main() with observer loop
└── tests/
    ├── __init__.py
    ├── conftest.py               # env var fixtures + mock missing modules
    ├── test_extension_filter.py  # 19 extension filter tests
    └── test_minio_key_scheme.py  # 6 MinIO key format/collision tests
```

### 6 State Transitions (AUTO-07)

All state transitions are logged as structured `logger.info` / `logger.error` lines:

| State | Trigger | Log Example |
|-------|---------|-------------|
| `DETECTED` | Video file event received | `DETECTED  /watch/holiday.mp4` |
| `STABLE` | File exists, stat succeeded | `STABLE    /watch/holiday.mp4  size=2147483648 bytes` |
| `UPLOADING` | MinIO fput_object started | `UPLOADING /watch/holiday.mp4` |
| `QUEUED` | Ingestion worker returned status≠skipped | `QUEUED    /watch/holiday.mp4  video_id=abc123` |
| `SKIPPED` | Non-video ext / file gone / already ingested | `SKIPPED   /watch/holiday.mp4  reason=non_video_extension` |
| `ERROR` | Any exception during upload/ingest | `ERROR     /watch/holiday.mp4  HTTPStatusError: 500` |

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED  | `579e278` | ✅ 25 tests collected, all ERROR — `ModuleNotFoundError: No module named 'app.watcher'` |
| GREEN | `aa43853` | ✅ 25 tests pass |

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — Write failing tests | `579e278` | 6 test/config files created |
| 2 | GREEN — Create watcher scaffold | `aa43853` | 7 implementation files created |
| 3 | .m4v patch to ingestion-worker | `76df032` | `ingestion-worker/app/main.py` modified |

## Verification Results

```
✅ services/watcher/Dockerfile — exists
✅ services/watcher/requirements.txt — exists
✅ services/watcher/app/config.py — exists
✅ services/watcher/app/storage.py — exists
✅ services/watcher/app/watcher.py — exists
✅ services/watcher/app/main.py — exists
✅ on_closed() defined at line 176 — on_created() NOT defined as method (only in comments)
✅ run_coroutine_threadsafe count = 4 (2 functional calls in on_closed + on_moved)
✅ All 6 state transitions present (DETECTED, STABLE, UPLOADING, QUEUED, SKIPPED, ERROR)
✅ PollingObserver + WATCH_USE_POLLING present in main.py
✅ startup_scan at line 28, observer.start() at line 47 (scan BEFORE start)
✅ .m4v present in ingestion-worker _VIDEO_EXTENSIONS
✅ 25 watcher tests pass (19 extension filter + 6 MinIO key scheme)
✅ 36 ingestion-worker tests pass (no regression)
```

## Deviations from Plan

**25 tests instead of 24** — The plan's `test_minio_key_scheme.py` listed 5 key format tests + 1 collision test = 6 MinIO key tests. Combined with 19 extension tests = 25 total. The plan's "done" criterion stated "24 passed" but the test file as written had a 6th format test (`test_key_for_filename_with_spaces`). All tests pass; this is a minor count discrepancy in the plan documentation, not an issue.

## Known Stubs

None — all functionality fully implemented. MinIO upload, HTTP POST, observer loop all wired. No placeholder data.

## Threat Surface Scan

No new network endpoints or auth paths introduced beyond what the plan documented. The watcher service:
- Reads files from bind-mounted volume (read-only when `:ro` applied in Plan 10-03)
- Writes to MinIO using credentials from env vars (`os.environ["MINIO_ACCESS_KEY"]` — fail-fast, T-10-02-01 mitigated)
- POSTs to internal Docker network endpoint (ingestion-worker:8001)
- No public-facing HTTP server — no new external trust boundary

## Self-Check: PASSED

- [x] `services/watcher/Dockerfile` — exists
- [x] `services/watcher/app/watcher.py` — exists with all required functions
- [x] `services/watcher/app/main.py` — exists with startup_scan + observer loop
- [x] `services/watcher/tests/test_extension_filter.py` — exists (19 tests)
- [x] `services/watcher/tests/test_minio_key_scheme.py` — exists (6 tests)
- [x] Commit `579e278` — exists (RED: test files)
- [x] Commit `aa43853` — exists (GREEN: implementation)
- [x] Commit `76df032` — exists (fix: .m4v patch)
- [x] 25 watcher tests pass
- [x] 36 ingestion-worker tests pass (no regression)
