---
phase: 04-web-ui
plan: "03"
subsystem: library-management-ui
tags: [react, typescript, tailwind, tanstack-query, nginx, html5-drag-drop, optimistic-ui]
dependency_graph:
  requires:
    - 04-01  # react scaffold, api hooks, types
  provides:
    - status-badge-component
    - videos-page
    - nginx-ingest-api-proxy
    - enrollment-dropzone-component
    - person-card-component
    - people-page
  affects:
    - services/web/src/components
    - services/web/src/pages
    - services/web/nginx.conf
tech_stack:
  added:
    - HTML5 FileReader API (file preview thumbnails)
    - HTML5 Drag and Drop API (native, no library)
  patterns:
    - React.Fragment with key for adjacent sibling rows in table
    - Optimistic UI via queryClient.setQueryData + rollback on error
    - noUnusedLocals/noUnusedParameters: strip unused imports at compile time
key_files:
  created:
    - services/web/src/components/StatusBadge.tsx
    - services/web/src/components/EnrollmentDropzone.tsx
    - services/web/src/components/PersonCard.tsx
  modified:
    - services/web/src/pages/VideosPage.tsx
    - services/web/src/pages/PeoplePage.tsx
    - services/web/nginx.conf
decisions:
  - "Used React.Fragment key={video.id} instead of <> to avoid React key warnings on sibling <tr> elements"
  - "Removed unused clsx import from PersonCard (noUnusedLocals strict rule)"
  - "Used (_n) parameter naming convention in PersonCard onSuccess to satisfy noUnusedParameters"
metrics:
  duration: "~15 minutes"
  completed: "2025-07-18"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 3
---

# Phase 4 Plan 3: Library Management UI Summary

**One-liner:** Color-coded StatusBadge, VideosPage table with Re-ingest action, nginx /ingest-api/ proxy to ingestion-worker, native HTML5 EnrollmentDropzone with file previews, PersonCard with inline confirm/rematch/enroll, and PeoplePage with optimistic add-person.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | StatusBadge + VideosPage + nginx reingest proxy | fe5f8ab | StatusBadge.tsx, VideosPage.tsx, nginx.conf |
| 2 | EnrollmentDropzone + PersonCard | 094c516 | EnrollmentDropzone.tsx, PersonCard.tsx |
| 3 | PeoplePage — person grid + optimistic add-person | ab50558 | PeoplePage.tsx |

## What Was Built

### StatusBadge (`services/web/src/components/StatusBadge.tsx`)
Color-coded pill badge for 4 video statuses: `pending`=gray, `processing`=blue+animate-pulse, `done`=green, `failed`=red. Falls back to gray for unknown status strings.

### VideosPage (`services/web/src/pages/VideosPage.tsx`)
Full table replacing stub. Shows filename (last path segment of minio_key), StatusBadge, frame/detection/face counts, ingested date. Re-ingest button disabled while `status === 'processing'` or in-flight. Error detail row shown below failed rows. Pagination, loading skeletons, empty state, no-token banner.

### nginx.conf — `/ingest-api/` proxy
Added location block after `/api/` that proxies to `ingestion-worker:8001/` with `Authorization` header forwarding. All existing location blocks (`/`, `/nginx-health`, `/api/`) preserved.

### EnrollmentDropzone (`services/web/src/components/EnrollmentDropzone.tsx`)
Native HTML5 drag-and-drop (no library). File input fallback. Per-file preview thumbnails via FileReader. FormData field name `images` (plural). Calls `useEnrollPerson().mutateAsync(formData)`. Shows rejected[] filenames + reasons and warning banner from EnrollResponse. On success: clears accepted files, keeps rejected visible.

### PersonCard (`services/web/src/components/PersonCard.tsx`)
Card showing name + enrollment count with warning if < 5. Three actions: Add photos (toggles inline EnrollmentDropzone), Rematch (shows updated count 4 seconds), Delete (inline confirm → useDeletePerson). Uses hook invalidation for re-fetch after mutations.

### PeoplePage (`services/web/src/pages/PeoplePage.tsx`)
Full page replacing stub. Add person form with optimistic update: prepends temp person to queryClient before API call, rolls back on error. Responsive grid (1/2/3/4 columns). Loading skeletons, empty state, no-token banner.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - TypeScript] Removed unused `clsx` import from PersonCard**
- **Found during:** Task 2 — TypeScript check with `noUnusedLocals: true`
- **Issue:** Plan code included `import clsx from 'clsx'` but PersonCard doesn't call `clsx()`
- **Fix:** Removed the unused import
- **Files modified:** `services/web/src/components/PersonCard.tsx`
- **Commit:** 094c516

**2. [Rule 2 - TypeScript] React.Fragment key for sibling table rows**
- **Found during:** Task 1 — critical constraint in plan
- **Issue:** Plan code uses `<>` wrapper in `.map()` which drops the React `key` prop
- **Fix:** Used `<React.Fragment key={video.id}>` + added `import React` for explicit usage
- **Files modified:** `services/web/src/pages/VideosPage.tsx`
- **Commit:** fe5f8ab

**3. [Rule 2 - TypeScript] Unused parameter `n` in PersonCard onSuccess**
- **Found during:** Task 2 — `noUnusedParameters: true` in tsconfig
- **Issue:** `onSuccess={(n) => {` — `n` is never used in the callback body
- **Fix:** Renamed to `(_n)` (TypeScript convention for intentionally unused params)
- **Files modified:** `services/web/src/components/PersonCard.tsx`
- **Commit:** 094c516

## Known Stubs

None — all stubs from Plan 01 have been replaced with full implementations.

## Threat Flags

None beyond what is addressed in the plan's threat model. All mitigations are in place:
- nginx forwards `Authorization` header to ingestion-worker (T-04-10, T-04-11)
- Client-side `image/*` filter + server-side InsightFace validation (T-04-12)
- React JSX text binding for minio_key and error_message (T-04-13, T-04-14)

## Self-Check: PASSED

Files exist:
- ✓ services/web/src/components/StatusBadge.tsx
- ✓ services/web/src/components/EnrollmentDropzone.tsx
- ✓ services/web/src/components/PersonCard.tsx
- ✓ services/web/src/pages/VideosPage.tsx (replaced stub)
- ✓ services/web/src/pages/PeoplePage.tsx (replaced stub)
- ✓ services/web/nginx.conf contains /ingest-api/

Commits:
- ✓ fe5f8ab — Task 1
- ✓ 094c516 — Task 2
- ✓ ab50558 — Task 3

TypeScript: compiles without errors (npx tsc --noEmit exit code 0)
