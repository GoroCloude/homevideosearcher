---
phase: 10-watch-folder-auto-ingest
plan: "01"
subsystem: ingestion-worker
tags: [concurrency, semaphore, oom-prevention, tdd, pipeline]
dependency_graph:
  requires: []
  provides: [pipeline-semaphore-guard]
  affects: [services/ingestion-worker/app/pipeline.py]
tech_stack:
  added: []
  patterns: [asyncio.Semaphore(1) concurrency guard, TDD RED/GREEN cycle]
key_files:
  created:
    - services/ingestion-worker/tests/test_pipeline_semaphore.py
  modified:
    - services/ingestion-worker/app/pipeline.py
decisions:
  - "Semaphore declared at module level (not inside function) so it is shared across all process_video calls in the same worker process"
  - "try/except/finally block nested INSIDE async with _pipeline_sem: so cleanup always runs while still holding correct serialization semantics"
  - "Semaphore value = 1 (binary mutex) — prevents two simultaneous ML runtimes from OOM-killing the 8 GB host"
metrics:
  duration: "~10 minutes"
  completed: "2025-01-28"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 10 Plan 01: Pipeline Semaphore Concurrency Guard Summary

**One-liner:** `asyncio.Semaphore(1)` added at module level in `pipeline.py` wrapping entire `process_video` body to serialize YOLO+InsightFace ML pipeline executions and prevent OOM kills on 8 GB host.

## What Was Built

Added a binary asyncio semaphore (`_pipeline_sem`) to `services/ingestion-worker/app/pipeline.py` that serializes all concurrent `process_video` calls. Without this guard, two simultaneous calls would each load YOLO (~1.5 GB RSS) + InsightFace (~2 GB RSS) = ~7 GB total RSS on an 8 GB host, triggering Docker OOM-kill. The watch-folder service (Plans 10-02 / 10-03) is the first mechanism that can trigger simultaneous ingest calls, so this guard must be in place before that service goes live.

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED  | `5add879` | ✅ 4 tests collected, all FAILED — `AttributeError: module 'app.pipeline' has no attribute '_pipeline_sem'` |
| GREEN | `0d1cdb6` | ✅ 36 tests pass including 4 new semaphore tests |

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED — Write failing semaphore tests | `5add879` | `tests/test_pipeline_semaphore.py` (created) |
| 2 | GREEN — Add _pipeline_sem to pipeline.py | `0d1cdb6` | `app/pipeline.py` (modified) |

## Changes Made

### `services/ingestion-worker/app/pipeline.py`
1. Added `import asyncio` to the import block (line 12)
2. Inserted module-level declaration after `# ── Main pipeline` banner:
   ```python
   _pipeline_sem: asyncio.Semaphore = asyncio.Semaphore(1)
   ```
3. Wrapped entire `process_video` body with `async with _pipeline_sem:` — the `try/except/finally` block is nested inside the `with` block so cleanup runs correctly under all conditions

### `services/ingestion-worker/tests/test_pipeline_semaphore.py` (new)
- `TestSemaphoreExists` (3 tests): verifies `_pipeline_sem` attribute exists, is `asyncio.Semaphore`, and has `_value == 1`
- `TestSemaphoreSerializes` (1 test): launches two concurrent `process_video` tasks and asserts that `end:aaa` appears in the event timeline before `start:bbb` — proving sequential (not parallel) execution

## Verification

```
grep -n "_pipeline_sem" services/ingestion-worker/app/pipeline.py
12: import asyncio        (asyncio imported)
161: _pipeline_sem: asyncio.Semaphore = asyncio.Semaphore(1)   (declaration)
174:     async with _pipeline_sem:   (exactly 1 usage wrapping body)

python -m pytest tests/ -v → 36 passed in 0.43s
```

## Deviations from Plan

None — plan executed exactly as written. All three edits (add import, insert declaration, wrap body) applied cleanly. All existing tests (face threshold ×12, YOLO class resolver ×20, semaphore ×4) pass GREEN.

## Known Stubs

None — this plan adds a concurrency guard only; no data stubs introduced.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The semaphore is the mitigation for T-10-01-01 (DoS via OOM). T-10-01-02 (error message disclosure) and T-10-01-03 (semaphore starvation) accepted per plan threat register.

## Self-Check: PASSED

- [x] `services/ingestion-worker/tests/test_pipeline_semaphore.py` — exists (created)
- [x] `services/ingestion-worker/app/pipeline.py` — modified (3 edits verified)
- [x] Commit `5add879` — exists (RED: test file)
- [x] Commit `0d1cdb6` — exists (GREEN: implementation)
- [x] `36 passed` — all tests green, no regressions
