---
phase: 09-person-appearance-page
plan: "01"
subsystem: api-backend, web-types
tags: [api, persons, appearances, presigned-url, typescript, tdd]

dependency_graph:
  requires:
    - "services/api/app/storage.py (generate_presigned_url)"
    - "services/api/app/config.py (MINIO_BUCKET_FRAMES)"
    - "services/api/app/db.py (get_pool)"
    - "face_detections table with matched_person_id"
    - "frames table with minio_key and ts_ms"
    - "videos table with minio_key, recorded_at, ingested_at, duration_sec"
  provides:
    - "GET /persons/{person_id}/appearances endpoint"
    - "VideoAppearance TypeScript interface"
    - "PersonAppearancesResponse TypeScript interface"
  affects:
    - "Wave 2 PersonAppearancePage component (consumes new endpoint + types)"

tech_stack:
  added: []
  patterns:
    - "CTE DISTINCT ON (video_id) ORDER BY ts_ms ASC — earliest frame per video"
    - "GROUP BY video_id — one result row per video"
    - "generate_presigned_url per row — server-side N+1 prevention"
    - "Two separate pool.acquire() calls — person-exists check then main query"
    - "TDD RED→GREEN — 7 tests written before implementation"

key_files:
  created:
    - path: "services/api/tests/test_person_appearances.py"
      role: "TDD test suite — 7 tests covering all behaviours of the endpoint"
  modified:
    - path: "services/api/app/persons.py"
      role: "Added generate_presigned_url import, VideoAppearanceItem model, PersonAppearancesResponse model, list_person_appearances endpoint"
    - path: "services/web/src/types/api.ts"
      role: "Appended VideoAppearance and PersonAppearancesResponse TypeScript interfaces"

decisions:
  - "Used two separate pool.acquire() calls (person-exists check + main query) following existing persons.py pattern"
  - "CTE DISTINCT ON picks earliest frame (lowest ts_ms) per video for thumbnail — avoids subquery in SELECT list"
  - "generate_presigned_url called server-side per result row to prevent N+1 browser MinIO requests"
  - "recorded_at uses COALESCE(v.recorded_at, v.ingested_at) for consistent sorting even when recorded_at is NULL"

metrics:
  duration: "~15 minutes"
  completed: "2025-01-31"
  tasks_completed: 2
  files_modified: 3
  tests_added: 7
  tests_passing: 54
---

# Phase 9 Plan 01: Person Appearances API Endpoint and TypeScript Types Summary

**One-liner:** `GET /persons/{id}/appearances` endpoint grouping face detections by video with server-side presigned thumbnails, plus matching TypeScript types for Wave 2.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for appearances endpoint | c115d0d | `tests/test_person_appearances.py` (+300 lines, 7 tests) |
| 1 (GREEN) | VideoAppearanceItem model + endpoint | dd21d87 | `app/persons.py` (+107 lines) |
| 2 | TypeScript VideoAppearance interfaces | ffc39d6 | `src/types/api.ts` (+16 lines) |

## What Was Built

### `GET /persons/{person_id}/appearances`

New endpoint in `services/api/app/persons.py` on the existing `/persons` router. No new router registration needed.

**Behaviour:**
- `GET /persons/<invalid-uuid>/appearances` → 422 (FastAPI UUID validation)
- `GET /persons/<unknown-uuid>/appearances` → 404 `{"detail": "Person not found"}`
- `GET /persons/<known-uuid>/appearances` → 200 with `{"person_id", "person_name", "results": [...]}`
- Results are one row **per video** (not per face detection) — multiple detections in one video collapse into `appearance_count`
- Results sorted newest-first by `COALESCE(v.recorded_at, v.ingested_at) DESC NULLS LAST`
- `thumbnail_url` is a presigned HTTPS URL generated server-side via `generate_presigned_url(bucket=config.MINIO_BUCKET_FRAMES, key=r["frame_minio_key"], expires_hours=1)`

**SQL approach:**  
CTE `first_frames` uses `DISTINCT ON (f.video_id) ORDER BY f.video_id, f.ts_ms ASC` to identify the frame with the lowest `ts_ms` per video. The main query uses `GROUP BY video_id` to aggregate appearance counts, then joins `first_frames` to get the thumbnail frame key.

### TypeScript Interfaces (types/api.ts)

```typescript
export interface VideoAppearance {
  video_id:         string;
  video_minio_key:  string;
  recorded_at:      string | null;
  duration_sec:     number | null;
  first_ts_ms:      number;
  appearance_count: number;
  thumbnail_url:    string;   // presigned URL — use directly in <img src>
}

export interface PersonAppearancesResponse {
  person_id:   string;
  person_name: string;
  results:     VideoAppearance[];
}
```

## TDD Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED (failing tests) | c115d0d | ✅ 7 tests failed as expected |
| GREEN (implementation) | dd21d87 | ✅ 7 tests passed |
| REFACTOR | (none needed) | — |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — endpoint is fully implemented with real SQL query. TypeScript interfaces are contracts for Wave 2 consumption.

## Threat Flags

No new threat surface beyond what was documented in the plan's `<threat_model>`:
- `T-09-01`: Presigned URLs in response body — accepted (1h TTL, bearer-gated endpoint)
- `T-09-02`: UUID path param injection — accepted (FastAPI validation + asyncpg parameterized query)
- `T-09-03`: Unbounded presigned URL loop — accepted (HMAC-only, no network I/O)

## Self-Check: PASSED

- `services/api/tests/test_person_appearances.py` — FOUND ✅
- `services/api/app/persons.py` (contains `list_person_appearances`) — FOUND ✅
- `services/web/src/types/api.ts` (contains `VideoAppearance`) — FOUND ✅
- Commit c115d0d (RED) — FOUND ✅
- Commit dd21d87 (GREEN) — FOUND ✅
- Commit ffc39d6 (TypeScript types) — FOUND ✅
- 54/54 tests passing — CONFIRMED ✅
- `npx tsc --noEmit` zero errors — CONFIRMED ✅
