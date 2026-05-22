---
phase: "07"
plan: "03"
subsystem: web-frontend
tags: [navigation, delete, headlessui, react-query]
dependency_graph:
  requires: [07-01, 07-02]
  provides: [row-navigation, per-row-delete]
  affects: [VideosPage]
tech_stack:
  added: []
  patterns: [row-click-navigation, stopPropagation-pattern, single-dialog-instance]
key_files:
  modified:
    - services/web/src/pages/VideosPage.tsx
decisions:
  - Single Dialog instance outside the row map loop — prevents N dialogs from being created
  - deleteTarget state drives both which row shows disabled Delete and which ID gets confirmed
  - stopPropagation on every button inside <tr> prevents dual-trigger with row onClick
metrics:
  duration: "~5 minutes"
  completed: "2025-07-11"
  tasks_completed: 1
  files_modified: 1
---

# Phase 7 Plan 03: VideosPage Extensions — Row Navigation + Delete Summary

## One-liner

Row-click navigation to `/videos/:id` plus per-row Delete with HeadlessUI confirmation dialog wired to `useDeleteVideo`.

## What Was Implemented

All changes are in `services/web/src/pages/VideosPage.tsx`:

### Imports added
- `useNavigate` added to `react-router-dom` import
- `useDeleteVideo` added to `../api/videos` import
- `Dialog, DialogPanel, DialogTitle` from `@headlessui/react`
- `addToast` from `../hooks/useToast`

### State & hooks added (inside component)
```typescript
const navigate = useNavigate();
const deleteMutation = useDeleteVideo();
const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
```

### New `handleDelete` function
Clears `deleteTarget` immediately (closes dialog), calls `deleteMutation.mutateAsync(id)`,
shows success toast on completion or error toast on failure.

### `<tr>` made clickable
- Added `cursor-pointer` class
- Added `onClick={() => navigate('/videos/${video.id}')}`

### Action column updated (3 buttons in flex row)
1. **Re-ingest** — existing button, now wraps handler in `e.stopPropagation()`
2. **↗ icon** — new button, navigates to detail page via `e.stopPropagation()` + `navigate()`
3. **Delete** — new button, opens confirmation via `e.stopPropagation()` + `setDeleteTarget(video.id)`

### Delete confirmation Dialog
Single `<Dialog>` instance outside the map loop, controlled by `deleteTarget !== null`.
Matches the HeadlessUI pattern used elsewhere in the project (VideoModal.tsx style).
Cancel clears `deleteTarget`; confirm calls `handleDelete(deleteTarget)`.

## TypeScript Verification

```
cd services/web && npx tsc --noEmit
```
**Result: 0 errors** ✅

## Commit

`74e8022` — `feat(web): add row-click navigation and delete to VideosPage`

## Deviations from Plan

None — plan executed exactly as written.

## Checkpoint: Human Verification Required

With `docker compose up` running, verify on the homeserver at `http://localhost:5173/videos`:

### Checklist

1. **Row click navigation**
   - [ ] Click anywhere on a video row body (not on a button) → navigates to `/videos/{id}` and renders the detail page
   - [ ] Click the ↗ icon → also navigates to `/videos/{id}`
   - [ ] Click `Re-ingest` → does NOT navigate; triggers re-ingest only
   - [ ] Click `Delete` → does NOT navigate; opens confirmation dialog

2. **Delete from Videos page**
   - [ ] Open confirmation dialog by clicking `Delete` on any row
   - [ ] Click `Cancel` → dialog closes, video still in list
   - [ ] Click `Delete` again, then confirm → video disappears from grid immediately (no page reload), success toast appears

3. **Delete from Detail page**
   - [ ] Navigate to any `/videos/{id}` detail page
   - [ ] Click `Delete Video` button → confirmation dialog appears
   - [ ] Confirm → navigates back to `/videos`, video no longer in list

4. **Search/cluster cache invalidation (DEL-04)**
   - [ ] Perform a search returning results that include a video you intend to delete
   - [ ] Delete the video from the Videos page
   - [ ] Navigate to Search → the deleted video's frames no longer appear

Type **"approved"** to confirm all four checks pass, or describe any issues found.

## Self-Check: PASSED

- File `services/web/src/pages/VideosPage.tsx` exists ✅
- Commit `74e8022` exists in git log ✅
- TypeScript: 0 errors ✅
