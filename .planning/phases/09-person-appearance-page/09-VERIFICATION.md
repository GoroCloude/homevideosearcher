---
phase: 09-person-appearance-page
verified: 2025-01-31T11:20:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Click a person card on /people — confirm browser navigates to /people/:id with no full-page reload"
    expected: "URL changes to /people/{uuid}, page renders PersonAppearancePage content (person name, video list), no network request for document reload"
    why_human: "SPA Link component wiring is verified in code, but actual browser navigation and absence of reload requires manual observation"
  - test: "On PersonAppearancePage with a person who appears in ≥1 video, click a video row — confirm VideoDetailPage opens and video is seeked to the correct timestamp"
    expected: "URL becomes /videos/{id}?t={first_ts_ms}, video player is positioned at that timestamp (not at 0:00), the frame matching the face detection is visible"
    why_human: "The seek useEffect fires when `video` data loads; the actual currentTime assignment depends on browser video metadata load timing and requires real MinIO stream_url to observe"
  - test: "Navigate to /videos/:id?t=5000 directly (valid video ID, t=5000) — confirm video player starts at 5.0 s"
    expected: "Video player currentTime = 5.0 immediately after load, not 0"
    why_human: "HTML5 seek via currentTime before loadedmetadata may silently fail on some browsers; only live testing with a real video can confirm"
---

# Phase 9: Person Appearance Page — Verification Report

**Phase Goal:** Person Appearance Page — clicking a known person on the People page navigates to `/people/:id`, which shows a timeline of all videos they appear in with face thumbnails, timestamps, and appearance counts; clicking any video row deep-links to the VideoDetailPage seeked to that timestamp.

**Verified:** 2025-01-31T11:20:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                                 | Status     | Evidence                                                                                                                                              |
|----|-------------------------------------------------------------------------------------------------------|------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | Clicking any person card on the People page navigates to `/people/:id` without a full page reload    | ✓ VERIFIED | `PersonCard.tsx` line 38–52: `<Link to={\`/people/${person.id}\`}>` wraps the name/avatar header; react-router-dom `Link` guarantees SPA navigation |
| 2  | Person detail page lists all videos newest-first: face thumbnail, first timestamp, appearance count  | ✓ VERIFIED | `PersonAppearancePage.tsx` lines 169–206: renders `appearances.map(a => ...)` with `<img src={a.thumbnail_url}>`, `fmtSeconds(a.first_ts_ms)`, and appearance count badge; server SQL uses `ORDER BY COALESCE(v.recorded_at, v.ingested_at) DESC NULLS LAST` in `persons.py` lines 527–535 |
| 3  | Clicking a video row opens VideoDetailPage seeked to the correct timestamp                           | ✓ VERIFIED | `PersonAppearancePage.tsx` line 172: `navigate(\`/videos/${a.video_id}?t=${a.first_ts_ms}\`)`; `VideoDetailPage.tsx` lines 43–56: `useSearchParams`, `seekToMs = searchParams.get('t')`, `useEffect([seekToMs, video])` calls `seek(Number(seekToMs))` when both `seekToMs` and `video` are truthy |
| 4  | `/people/:id` for non-existent person → 404 state; person with no detections → empty state          | ✓ VERIFIED | API `persons.py` lines 498–499: `HTTPException(status_code=404, detail="Person not found")`; `PersonAppearancePage.tsx` lines 92–106: renders error banner on `isError`; lines 161–164: renders "No appearances found" when `appearances.length === 0` |
| 5  | `/videos/:id?t=12345` on mount seeks the video player to that timestamp                              | ✓ VERIFIED | `VideoDetailPage.tsx` lines 2, 43–56, 70–72: `useSearchParams` imported from react-router-dom, `seekToMs` read from `?t=`, `useEffect` placed before no-token guard (respects Rules of Hooks), calls `seek(Number(seekToMs))` which sets `videoRef.current.currentTime = ts_ms / 1000` |

**Score: 5/5 truths verified**

---

### Required Artifacts

| Artifact                                            | Expected                                                  | Status     | Details                                                                                                     |
|-----------------------------------------------------|-----------------------------------------------------------|------------|-------------------------------------------------------------------------------------------------------------|
| `services/api/app/persons.py`                       | GET /persons/{id}/appearances endpoint                    | ✓ VERIFIED | Lines 458–561: `VideoAppearanceItem`, `PersonAppearancesResponse` Pydantic models + `list_person_appearances` endpoint. `generate_presigned_url` imported line 20. Full CTE SQL query grouping per video. |
| `services/web/src/types/api.ts`                     | VideoAppearance + PersonAppearancesResponse interfaces    | ✓ VERIFIED | Lines 148–162: both interfaces exported with correct field types matching API response shape                |
| `services/web/src/api/persons.ts`                   | getPersonAppearances + usePersonAppearances               | ✓ VERIFIED | Lines 88–100: `getPersonAppearances` calls `authFetch('/persons/${personId}/appearances')`, `usePersonAppearances` uses TanStack Query v5 object-form with `enabled: !!apiToken && !!personId` |
| `services/web/src/pages/PersonAppearancePage.tsx`   | New page at /people/:id                                   | ✓ VERIFIED | 254-line component: person header, newest-first video list, month timeline, no-token/loading/error/empty states. No stubs or TODOs found. |
| `services/web/src/components/PersonCard.tsx`        | Link wrap navigating to /people/{id}                      | ✓ VERIFIED | Lines 38–52: `<Link to={\`/people/${person.id}\`}>` wraps name/avatar; action buttons remain outside Link  |
| `services/web/src/pages/VideoDetailPage.tsx`        | useSearchParams + useEffect seek                          | ✓ VERIFIED | Lines 2, 43–56, 70–72: `useSearchParams` imported, `seekToMs` extracted from `?t=`, `useEffect` before no-token guard, `seek()` sets `currentTime`  |
| `services/web/src/App.tsx`                          | /people/:id route                                         | ✓ VERIFIED | Line 19: `<Route path="people/:id" element={<PersonAppearancePage />} />` adjacent to `people` route      |
| `services/api/tests/test_person_appearances.py`     | 7 TDD tests for API endpoint                              | ✓ VERIFIED | File exists (300+ lines); TDD RED commit c115d0d, GREEN commit dd21d87                                     |
| `services/web/src/__tests__/person-appearances.test.ts`   | 6 TDD tests for getPersonAppearances hook          | ✓ VERIFIED | File exists; 6 tests pass in vitest run                                                                     |
| `services/web/src/__tests__/PersonAppearancePage.test.tsx` | 11 TDD tests for PersonAppearancePage component   | ✓ VERIFIED | File exists; 11 tests pass in vitest run                                                                    |

---

### Key Link Verification

| From                           | To                                   | Via                                                  | Status     | Details                                                                                                |
|--------------------------------|--------------------------------------|------------------------------------------------------|------------|--------------------------------------------------------------------------------------------------------|
| PersonCard header              | `/people/:id` route                  | `<Link to=\`/people/${person.id}\`>` (react-router) | ✓ WIRED    | PersonCard.tsx:38–52                                                                                   |
| `people/:id` route             | PersonAppearancePage component       | Route in App.tsx                                     | ✓ WIRED    | App.tsx:19                                                                                             |
| PersonAppearancePage           | `GET /persons/{id}/appearances`      | `usePersonAppearances` → `getPersonAppearances` → `authFetch` | ✓ WIRED | persons.ts:88–100; PersonAppearancePage.tsx:3, 66 |
| Video row click                | VideoDetailPage at timestamp         | `navigate(\`/videos/${a.video_id}?t=${a.first_ts_ms}\`)` | ✓ WIRED | PersonAppearancePage.tsx:172, 232                                                                   |
| `?t=` URL param                | `videoRef.current.currentTime`       | `useSearchParams` + `useEffect` + `seek()`           | ✓ WIRED    | VideoDetailPage.tsx:43–56, 70–72                                                                       |
| API endpoint                   | PostgreSQL via CTE                   | `conn.fetch(CTE SQL, person_id)` in asyncpg          | ✓ WIRED    | persons.py:501–538; DISTINCT ON + GROUP BY + presigned URL generation                                 |
| thumbnail_url generation       | MinIO MINIO_BUCKET_FRAMES            | `generate_presigned_url(bucket=config.MINIO_BUCKET_FRAMES, key=r["frame_minio_key"])` | ✓ WIRED | persons.py:548–553 |

---

### Data-Flow Trace (Level 4)

| Artifact                      | Data Variable   | Source                                               | Produces Real Data | Status      |
|-------------------------------|-----------------|------------------------------------------------------|--------------------|-------------|
| PersonAppearancePage.tsx      | `data.results`  | `usePersonAppearances` → `GET /persons/{id}/appearances` → PostgreSQL CTE | ✓ Real DB query, no static returns | ✓ FLOWING |
| VideoDetailPage.tsx (seek)    | `seekToMs`      | `useSearchParams().get('t')` from URL query string   | ✓ URL param set by PersonAppearancePage navigate call | ✓ FLOWING |
| persons.py endpoint           | `results` list  | `conn.fetch(CTE SQL)` with `face_detections JOIN frames JOIN videos` | ✓ Live asyncpg query, no static `return []` | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior                               | Command                                                                                        | Result                   | Status  |
|----------------------------------------|------------------------------------------------------------------------------------------------|--------------------------|---------|
| 36 frontend tests pass                 | `cd services/web && npm test -- --run`                                                        | 36/36 passed in 6.42s    | ✓ PASS  |
| PersonAppearancePage test suite        | `vitest run src/__tests__/PersonAppearancePage.test.tsx`                                      | 11/11 passed             | ✓ PASS  |
| person-appearances hook tests          | `vitest run src/__tests__/person-appearances.test.ts`                                         | 6/6 passed               | ✓ PASS  |
| Git commits exist (all 5 wave commits) | `git log --oneline` shows c115d0d, dd21d87, ffc39d6, 3c867a6, 5ffc1d9, 8df54e1, 167ba8a, 74ae225 | All 8 commits present | ✓ PASS  |
| API service running / pytest           | Not runnable without Docker (API requires PostgreSQL + MinIO)                                 | —                        | ? SKIP  |

---

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                     | Status      | Evidence                                                                                                                  |
|-------------|-------------|-------------------------------------------------------------------------------------------------|-------------|---------------------------------------------------------------------------------------------------------------------------|
| PAP-01      | 09-02       | Clicking a known person on People page navigates to `/people/:id`                              | ✓ SATISFIED | PersonCard.tsx `<Link to=\`/people/${person.id}\`>`, App.tsx route `people/:id`                                          |
| PAP-02      | 09-01, 09-02| Person detail page lists all videos with face thumbnail, first timestamp, appearance count; sorted newest-first | ✓ SATISFIED | API CTE SQL ORDER BY DESC; PersonAppearancePage renders thumbnail, `fmtSeconds(a.first_ts_ms)`, appearance badge           |
| PAP-03      | 09-02       | Person detail page shows chronological timeline/calendar of appearance dates                    | ✓ SATISFIED | PersonAppearancePage.tsx lines 211–248: `groupByMonth()` renders month-grouped timeline, oldest first, "Unknown Date" at end |
| PAP-04      | 09-02       | Clicking a video appearance navigates to `/videos/:id?t={ts_ms}`                               | ✓ SATISFIED | PersonAppearancePage.tsx lines 172, 232: `navigate(\`/videos/${a.video_id}?t=${a.first_ts_ms}\`)`                        |
| PAP-05      | 09-02       | VideoDetailPage reads `?t=ts_ms` URL param on mount and seeks video player to that timestamp    | ✓ SATISFIED | VideoDetailPage.tsx: `useSearchParams`, `seekToMs`, `useEffect([seekToMs, video])` → `seek(Number(seekToMs))` → `videoRef.current.currentTime = ts_ms / 1000` |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | No TODOs, FIXMEs, empty stubs, or placeholder returns detected in any of the 6 key files |

---

### Human Verification Required

#### 1. SPA navigation on PersonCard click

**Test:** Open the People page (`/people`). Click a person card's name or avatar. Observe browser URL bar and network tab.
**Expected:** URL changes to `/people/{uuid}` without a full-page document reload. PersonAppearancePage content renders (person name, video count, video list or empty state).
**Why human:** `Link` from react-router-dom guarantees SPA push-state navigation in code, but confirming the absence of a full reload and correct page rendering requires a live browser.

---

#### 2. Video row click seeks to correct timestamp

**Test:** Open a PersonAppearancePage for a person with at least 1 video appearance. Click a video row.
**Expected:** Browser navigates to `/videos/{id}?t={ms}`. The video player starts or seeks to the timestamp shown as "First at X.Xs" on the row (e.g., if the row shows "First at 5.2s", the video player should be at 5.2 s).
**Why human:** The seek `useEffect` fires after `video` API data loads (not after `loadedmetadata`); actual video scrubbing depends on browser HTMLVideoElement behavior with the presigned stream URL.

---

#### 3. Direct URL `/videos/:id?t=12345` seeks on mount

**Test:** Navigate directly (or hard-reload) to `/videos/{valid-id}?t=5000`.
**Expected:** Video player's current position is 5.0 s (not 0:00) after the stream URL loads.
**Why human:** HTML5 `currentTime` assignment before `loadedmetadata` fires is technically valid (sets a pending seek) but behaviour can vary across browsers; real MinIO stream needed to observe.

---

### Gaps Summary

No gaps blocking goal achievement. All 5 success criteria are fully implemented and wired:

- **PAP-01** — PersonCard wraps header in `<Link to=\`/people/${person.id}\`>`
- **PAP-02** — API returns newest-first via SQL; page renders thumbnail + first_ts_ms + appearance count badge
- **PAP-03** — `groupByMonth()` builds chronological timeline with sticky month headers
- **PAP-04** — Both video list rows and timeline rows call `navigate(\`/videos/${a.video_id}?t=${a.first_ts_ms}\`)`
- **PAP-05** — `useSearchParams` + `useEffect([seekToMs, video])` + `seek(Number(seekToMs))` in VideoDetailPage

The 3 human verification items above are visual/runtime behavioral checks that require a live browser + running stack. They do not represent code deficiencies.

---

_Verified: 2025-01-31T11:20:00Z_
_Verifier: the agent (gsd-verifier)_
