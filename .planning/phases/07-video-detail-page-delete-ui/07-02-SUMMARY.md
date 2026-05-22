---
phase: "07"
plan: "02"
subsystem: web-frontend
tags: [react, video-detail, delete, routing, headlessui]
dependency_graph:
  requires: [07-01]
  provides: [VideoDetailPage, /videos/:id route]
  affects: [App.tsx, routing]
tech_stack:
  added: []
  patterns: [useParams, useRef video seek, Headless UI Dialog, addToast singleton, no-token guard]
key_files:
  created:
    - services/web/src/pages/VideoDetailPage.tsx
  modified:
    - services/web/src/App.tsx
decisions:
  - Used addToast singleton (not hook) for delete feedback — matches plan spec
  - No-token guard placed after all hook calls (React rules) but before loading/error rendering
metrics:
  duration: "~5 minutes"
  completed: "2025-01-31"
  tasks_completed: 2
  files_created: 1
  files_modified: 1
---

# Phase 7 Plan 02: VideoDetailPage Component + App Route Summary

**One-liner:** Full-page video detail view at `/videos/:id` with HTML5 player, detection/face tabs, timeline seek bar, and confirmed delete flow using Headless UI Dialog.

## What Was Implemented

### Task 1 — `VideoDetailPage.tsx` (created)

A complete React page component (`services/web/src/pages/VideoDetailPage.tsx`) providing:

- **No-token guard** — amber banner matching app-standard pattern from `VideosPage.tsx`, placed after all hook calls
- **Metadata header** — `<dl>` grid showing filename (monospace), status, duration (m:ss), recorded_at, ingested_at (both via `fmtDate` with `date-fns` + try/catch guard)
- **HTML5 `<video>` player** — `ref={videoRef}`, `src={video.stream_url}`, `controls`, max-h-96
- **Tabbed content panel** — `useState<'detections' | 'faces'>` drives two grids:
  - **Detections tab** — 2–4 col responsive grid; cards show thumbnail (presigned URL via `<img src>`), label, confidence %, timestamp in seconds
  - **Faces tab** — same grid layout; cards show thumbnail, person_name, timestamp. When `faces.length > 0 && video.duration_sec != null`, renders a **timeline bar** with click-to-seek buttons positioned by `(ts_ms / duration_sec * 1000) * 100%`
- **`seek(ts_ms)`** helper: `videoRef.current.currentTime = ts_ms / 1000`
- **Delete button** → Headless UI `<Dialog>` confirmation → `deleteMutation.mutateAsync(id!)` → `addToast('Video deleted', 'success')` → `navigate('/videos', { replace: true })`
- **Loading skeleton** — 3 animated pulse divs
- **Error state** — red banner + "← Back to Videos" button

### Task 2 — `App.tsx` (modified)

- Added `import VideoDetailPage from './pages/VideoDetailPage'`
- Inserted `<Route path="videos/:id" element={<VideoDetailPage />} />` inside the `<Route path="/" element={<Layout />}>` wrapper, between `settings` route and wildcard catch-all

## New / Modified Files

| File | Action | Lines |
|------|--------|-------|
| `services/web/src/pages/VideoDetailPage.tsx` | Created | 257 |
| `services/web/src/App.tsx` | Modified | 26 (+3) |

## TypeScript Verification

```
cd services/web && npx tsc --noEmit
```

**Result: ✅ Zero errors** (exit code 0)

## Git Commit

```
e7152f2  feat(web): add VideoDetailPage with metadata, player, detection/face tabs, delete
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `services/web/src/pages/VideoDetailPage.tsx` — ✅ exists
- `services/web/src/App.tsx` — ✅ modified with import and route
- Commit `e7152f2` — ✅ exists in git log
- TypeScript — ✅ zero errors
