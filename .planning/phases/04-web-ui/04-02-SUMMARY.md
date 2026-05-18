---
phase: 04-web-ui
plan: "02"
subsystem: search-ui
tags: [react, tailwind, headlessui, tanstack-query, typescript]
dependency_graph:
  requires:
    - frames-router-public
    - api-hook-layer
    - react-scaffold
  provides:
    - layout-shell
    - frame-thumbnail-component
    - video-modal-component
    - search-page
  affects:
    - services/web/src/components
    - services/web/src/pages
tech_stack:
  added: []
  patterns:
    - Headless UI Dialog for accessible modal (focus trap, Escape key, backdrop click)
    - Pending/applied filter split-state pattern (apply on button click, not live)
    - FrameThumbnail with animate-pulse skeleton via onLoad/onError events
key_files:
  created:
    - services/web/src/components/FrameThumbnail.tsx
    - services/web/src/components/VideoModal.tsx
  modified:
    - services/web/src/components/Layout.tsx
    - services/web/src/pages/SearchPage.tsx
decisions:
  - "Split pending/applied filter state prevents live-refetch on every keystroke"
  - "FrameThumbnail uses <img> directly (no authFetch) because frames router is public"
  - "VideoModal reuses FrameThumbnail for consistency + skeleton in modal"
metrics:
  duration: "~20 minutes"
  completed: "2026-05-18"
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 2
---

# Phase 4 Plan 02: Search Page Summary

**One-liner:** Full search UI with desktop sidebar nav, FrameThumbnail skeleton loader, Headless UI VideoModal with Play-in-video, and SearchPage with filter sidebar, results grid, and pagination.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Layout shell + FrameThumbnail component | 4fdcb3b | Layout.tsx (replaced stub), FrameThumbnail.tsx (new) |
| 2 | VideoModal component | 0eddf4a | VideoModal.tsx (new) |
| 3 | SearchPage — filter sidebar, results grid, pagination | e902e79 | SearchPage.tsx (replaced stub) |

## What Was Built

### Layout.tsx (replaced stub)

Desktop sidebar (`hidden sm:flex`) with `NavLink` items for 5 routes. `end={item.to === '/'}` prevents root route matching all paths. Active route: `bg-blue-50 text-blue-700 border-r-2 border-blue-600`. Mobile bottom tab bar (`sm:hidden fixed bottom-0`) with icon-only nav (`sr-only` labels). `pb-16 sm:pb-0` on `<main>` prevents content hidden behind mobile bar.

### FrameThumbnail.tsx (new)

`<img src={getFrameImageUrl(frameId)}>` — no auth header required (frames router is public). `animate-pulse` skeleton (`absolute inset-0 bg-gray-300`) shown while `!loaded && !error`. Error state shows `⚠ No image`. `loading="lazy"` for performance. Accessible: `role="button"` and `onKeyDown` when `onClick` provided.

### VideoModal.tsx (new)

Headless UI `Dialog` wraps content. Backdrop click and Escape key close the modal (built-in). Shows `FrameResult`: thumbnail via `FrameThumbnail`, detection labels with confidence %, face names with `match_tier` badges (green=confident, yellow=probable). "Play in video" button: `authFetch(/videos/{id}/stream-url)` → `window.open(url + '#t=' + seconds, '_blank', 'noopener,noreferrer')`. Loading spinner and inline error message for stream URL fetch.

### SearchPage.tsx (replaced stub)

Default landing page (`/`). Split filter state: `pendingFilters` (live UI state) / `appliedFilters` (triggers query). Apply button commits pending → applied with `page: 1` reset. Filter sidebar: person checkboxes from `usePersons()`, 9 class checkboxes, date range `<input type="date">`, include-unknowns toggle. Desktop: `hidden md:block w-64` fixed sidebar. Mobile: collapsible drawer with `fixed inset-0 z-40` overlay. Results grid: `grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4`. 12 skeleton boxes during `isLoading`. Empty state: "No results — try different filters". Pagination: up to 7 page buttons + prev/next. No-token amber banner links to `/settings`. Clicking thumbnail → `setSelectedFrame(frame)` → opens `VideoModal`.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None in this plan. All stubs from Plan 01 replaced:
- `Layout.tsx` — fully implemented
- `SearchPage.tsx` — fully implemented

Remaining Plan 01 stubs (to be replaced in Plans 03–04):
- `src/pages/VideosPage.tsx`
- `src/pages/PeoplePage.tsx`
- `src/pages/ClustersPage.tsx`
- `src/pages/SettingsPage.tsx`

## Threat Flags

None — all threat model items implemented via React JSX text binding (T-04-06, T-04-07) and `enabled: !!apiToken` in useSearch (T-04-09). T-04-08 accepted per plan.

## Self-Check: PASSED

Files exist:
- services/web/src/components/Layout.tsx ✓
- services/web/src/components/FrameThumbnail.tsx ✓
- services/web/src/components/VideoModal.tsx ✓
- services/web/src/pages/SearchPage.tsx ✓

Commits exist:
- 4fdcb3b: feat(04-02): Layout shell + FrameThumbnail ✓
- 0eddf4a: feat(04-02): VideoModal ✓
- e902e79: feat(04-02): SearchPage ✓

TypeScript: no errors (npx tsc --noEmit passed after each task)
