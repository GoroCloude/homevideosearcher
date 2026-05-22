---
phase: 09-person-appearance-page
plan: "02"
subsystem: web-frontend
tags: [react, tanstack-query, react-router-dom, tdd, navigation, seek]

dependency_graph:
  requires:
    - "Wave 1 (09-01): GET /persons/{id}/appearances endpoint"
    - "Wave 1 (09-01): VideoAppearance + PersonAppearancesResponse TypeScript interfaces"
    - "services/web/src/api/persons.ts (existing authFetch + getSettings)"
    - "services/web/src/context/SettingsContext (useSettings)"
    - "date-fns (format, parseISO)"
  provides:
    - "getPersonAppearances() raw API fn"
    - "usePersonAppearances() TanStack Query v5 hook"
    - "PersonAppearancePage component at /people/:id"
    - "people/:id route in App.tsx"
    - "PersonCard header Link to /people/{id}"
    - "VideoDetailPage ?t= seek-on-mount via useSearchParams + useEffect"
  affects:
    - "PeoplePage (PersonCard now navigates to appearance page)"
    - "VideoDetailPage (now reads ?t= URL param and seeks player on mount)"

tech_stack:
  added: []
  patterns:
    - "useSearchParams (react-router-dom) — new pattern to codebase"
    - "useEffect([seekToMs, video]) — defer seek until stream_url loaded"
    - "groupByMonth() — sort + Map accumulation for chronological timeline"
    - "TanStack Query v5 object-form useQuery with enabled guard"
    - "React Rules of Hooks — useEffect + useSearchParams placed BEFORE conditional returns"

key_files:
  created:
    - path: "services/web/src/pages/PersonAppearancePage.tsx"
      role: "Full person appearance page: header, video list, month timeline, 404/empty states"
    - path: "services/web/src/__tests__/person-appearances.test.ts"
      role: "TDD RED→GREEN tests for getPersonAppearances and usePersonAppearances (6 tests)"
    - path: "services/web/src/__tests__/PersonAppearancePage.test.tsx"
      role: "TDD RED→GREEN tests for PersonAppearancePage component (11 tests)"
  modified:
    - path: "services/web/src/api/persons.ts"
      role: "Added getPersonAppearances raw fn + usePersonAppearances hook + PersonAppearancesResponse import"
    - path: "services/web/src/App.tsx"
      role: "Added PersonAppearancePage import + people/:id route"
    - path: "services/web/src/components/PersonCard.tsx"
      role: "Added Link import; wrapped name/avatar header in Link to /people/{person.id}"
    - path: "services/web/src/pages/VideoDetailPage.tsx"
      role: "Added useEffect + useSearchParams imports; added searchParams + seekToMs + seek useEffect before no-token guard"

decisions:
  - "Placed useSearchParams + seekToMs + useEffect BEFORE no-token guard in VideoDetailPage (React Rules of Hooks)"
  - "seek() is a function declaration — hoisted within component scope so useEffect can call it before its textual position"
  - "useEffect deps: [seekToMs, video] — video dep ensures stream_url is set before seeking"
  - "Timeline groupByMonth sorts chronologically (oldest first) using localeCompare on ISO strings"
  - "Null recorded_at items grouped under 'Unknown Date' pushed to end of timeline (after all dated groups)"
  - "TDD RED test for Task 2 fixed selector: used 'First at 5.0s' text to find video row buttons (avoids ambiguity with date text appearing in header dateRange)"

metrics:
  duration: "~20 minutes"
  completed: "2025-01-31"
  tasks_completed: 3
  files_modified: 5
  files_created: 3
  tests_added: 17
  tests_passing: 36
---

# Phase 9 Plan 02: Person Appearance Page Frontend Summary

**One-liner:** React frontend for person appearance page — TanStack Query v5 hook, month-timeline page, SPA navigation, and VideoDetailPage seek-on-mount via `useSearchParams`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for API hook | 3c867a6 | `__tests__/person-appearances.test.ts` (6 tests) |
| 1 (GREEN) | getPersonAppearances + usePersonAppearances | 5ffc1d9 | `api/persons.ts` (+17 lines) |
| 2 (RED) | Failing tests for PersonAppearancePage | 8df54e1 | `__tests__/PersonAppearancePage.test.tsx` (11 tests) |
| 2 (GREEN) | PersonAppearancePage component | 167ba8a | `pages/PersonAppearancePage.tsx` (+212 lines), test fix |
| 3 | Route, PersonCard link, VideoDetailPage seek | 74ae225 | `App.tsx`, `PersonCard.tsx`, `VideoDetailPage.tsx` |

## What Was Built

### `getPersonAppearances` + `usePersonAppearances` (`api/persons.ts`)

```typescript
export async function getPersonAppearances(personId: string): Promise<PersonAppearancesResponse> {
  return authFetch(`/persons/${personId}/appearances`).then(r => r.json());
}

export function usePersonAppearances(personId: string) {
  const { apiToken } = getSettings();
  return useQuery({
    queryKey:  ['person-appearances', personId],
    queryFn:   () => getPersonAppearances(personId),
    staleTime: 30_000,
    enabled:   !!apiToken && !!personId,
  });
}
```

### `PersonAppearancePage.tsx`

Full page at `/people/:id` with three sections:
1. **Person header** — name, avatar emoji, video count, total face appearances, date range
2. **Video list** — newest-first rows (server order), each with face thumbnail, formatted date, first timestamp, appearance count badge; clicking navigates to `/videos/{id}?t={first_ts_ms}`
3. **Appearance timeline** — appearances grouped by month, sorted chronologically oldest-first, sticky month headers with video count; null `recorded_at` items in "Unknown Date" group at end

**States handled:**
- No-token → amber banner with Settings link
- Loading → 3-bar skeleton with `animate-pulse`
- Error/404 → red banner + "← Back to People" button
- Empty → grey 🎞️ icon + "No appearances found" message (not an error state)

### Route: `people/:id` (`App.tsx`)

```tsx
<Route path="people"   element={<PeoplePage />} />
<Route path="people/:id" element={<PersonAppearancePage />} />
```

### PersonCard navigation link (`PersonCard.tsx`)

```tsx
import { Link } from 'react-router-dom';
// ...
<Link to={`/people/${person.id}`} className="flex items-start justify-between gap-2 hover:opacity-80 transition-opacity">
  {/* name + avatar header */}
</Link>
// Action buttons (Add photos, Rematch, Delete) remain outside Link — work independently
```

### VideoDetailPage `?t=` seek (`VideoDetailPage.tsx`)

```tsx
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom';

// Inside VideoDetailPage(), BEFORE no-token guard:
const [searchParams] = useSearchParams();
const seekToMs = searchParams.get('t');

useEffect(() => {
  if (seekToMs && video && videoRef.current) {
    seek(Number(seekToMs));
  }
}, [seekToMs, video]);
```

`seek()` is a function declaration and is hoisted within the component function scope, allowing the `useEffect` to call it before its textual position in the file.

## TDD Compliance

| Task | Gate | Commit | Status |
|------|------|--------|--------|
| 1 | RED (failing tests) | 3c867a6 | ✅ 6 tests failed — exports not yet present |
| 1 | GREEN (implementation) | 5ffc1d9 | ✅ 6 tests passed |
| 2 | RED (failing tests) | 8df54e1 | ✅ import failed — file not yet created |
| 2 | GREEN (implementation) | 167ba8a | ✅ 11 tests passed |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ambiguous test selector for video row click test**

- **Found during:** Task 2 GREEN
- **Issue:** Test used `getAllByText(/Mar 15, 2024/i)` to find video row buttons, but "Mar 15, 2024" also appeared in the header's `dateRange` `<dd>` element (which is NOT inside a `<button>`). `closest('button')` on the `<dd>` returned null, causing 1/11 tests to fail.
- **Fix:** Changed selector to `getAllByRole('button').find(btn => btn.textContent?.includes('First at 5.0s'))` — "First at 5.0s" is unique to video list rows (not present in header or timeline compact view).
- **Files modified:** `services/web/src/__tests__/PersonAppearancePage.test.tsx`
- **Commit:** 167ba8a (GREEN commit)

## Known Stubs

None — PersonAppearancePage is fully wired to the real API via `usePersonAppearances`. All data displayed (person name, video list, thumbnails, timestamps, appearance counts) comes from the live `/persons/{id}/appearances` endpoint delivered in Wave 1.

## Threat Flags

No new threat surface beyond the plan's `<threat_model>`:
- T-09-04: XSS via `data.person_name` — React JSX auto-escapes, no `dangerouslySetInnerHTML`
- T-09-05: Open redirect via `navigate(...)` — video_id and first_ts_ms are server-supplied typed fields
- T-09-06: `?t=` in browser history — timestamps are non-sensitive video offsets
- T-09-07: `seek(Number(seekToMs))` with crafted value — `Number('bad')` → NaN; HTML5 video ignores NaN currentTime

## Self-Check: PASSED

- `services/web/src/api/persons.ts` (contains `usePersonAppearances`) — FOUND ✅
- `services/web/src/pages/PersonAppearancePage.tsx` — FOUND ✅
- `services/web/src/App.tsx` (contains `people/:id`) — FOUND ✅
- `services/web/src/components/PersonCard.tsx` (contains `/people/`) — FOUND ✅
- `services/web/src/pages/VideoDetailPage.tsx` (contains `useSearchParams`, `seekToMs`) — FOUND ✅
- `services/web/src/__tests__/person-appearances.test.ts` — FOUND ✅
- `services/web/src/__tests__/PersonAppearancePage.test.tsx` — FOUND ✅
- Commit 3c867a6 (Task 1 RED) — FOUND ✅
- Commit 5ffc1d9 (Task 1 GREEN) — FOUND ✅
- Commit 8df54e1 (Task 2 RED) — FOUND ✅
- Commit 167ba8a (Task 2 GREEN) — FOUND ✅
- Commit 74ae225 (Task 3) — FOUND ✅
- `npx tsc --noEmit` zero errors — CONFIRMED ✅
- 36/36 tests passing — CONFIRMED ✅
