---
phase: 03-intelligence-telegram
plan: "03"
subsystem: web-frontend
tags: [clusters, react, tanstack-query, ignore, promote, restore]
dependency_graph:
  requires:
    - "03-01"  # Phase 3 API endpoints (promote, ignore, restore)
  provides:
    - cluster-ignore-ui
    - cluster-promote-ui
    - cluster-restore-ui
  affects:
    - services/web/src/types/api.ts
    - services/web/src/api/clusters.ts
    - services/web/src/components/ClusterCard.tsx
    - services/web/src/pages/ClustersPage.tsx
tech_stack:
  added: []
  patterns:
    - TanStack Query v5 useMutation with onSuccess invalidation
    - showRestoreOnly prop pattern for multi-mode card component
key_files:
  created: []
  modified:
    - services/web/src/types/api.ts
    - services/web/src/api/clusters.ts
    - services/web/src/components/ClusterCard.tsx
    - services/web/src/pages/ClustersPage.tsx
decisions:
  - "Defensive filter: ClustersPage filters activeClusters = clusters.filter(c => !c.ignored) even though API should exclude ignored from default list"
  - "showRestoreOnly prop on ClusterCard avoids a separate IgnoredClusterCard component — same card, different action set"
  - "handleIgnore/handleRestore swallow errors silently — query invalidation ensures UI refreshes to correct state"
  - "useIgnoredClusters uses queryKey ['clusters', 'ignored'] — separate from ['clusters'] so both can be invalidated independently"
metrics:
  duration: "~15 minutes"
  completed: "2025-01-31"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 4
---

# Phase 03 Plan 03: Cluster Promote / Ignore / Restore UI Summary

**One-liner:** Wired cluster promote (POST /clusters/{id}/promote), ignore (POST /clusters/{id}/ignore), and restore (DELETE /clusters/{id}/ignore) actions into the React frontend with a collapsed Ignored section on ClustersPage.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | TypeScript types + API hooks | `83f2b39` | `api.ts`, `clusters.ts` |
| 2 | ClusterCard + ClustersPage UI | `eded1a8` | `ClusterCard.tsx`, `ClustersPage.tsx` |

## What Was Built

### Task 1 — TypeScript types + API hooks
- **`api.ts`:** Added `ignored: boolean` to `ClusterItem` interface (alignment-style match)
- **`clusters.ts`:** Added 4 new exports:
  - `useIgnoredClusters()` — `useQuery` calling `GET /clusters?include_ignored=true`, queryKey `['clusters', 'ignored']`
  - `usePromoteCluster()` — `useMutation` calling `POST /clusters/{id}/promote?person_id={personId}`, invalidates `['clusters']`, `['clusters', 'ignored']`, `['persons']`
  - `useIgnoreCluster()` — `useMutation` calling `POST /clusters/{id}/ignore`, invalidates both cluster query keys
  - `useRestoreCluster()` — `useMutation` calling `DELETE /clusters/{id}/ignore`, invalidates both cluster query keys

### Task 2 — ClusterCard + ClustersPage UI
- **`ClusterCard.tsx`:**
  - Replaced `useRematchPerson` import with `usePromoteCluster`, `useIgnoreCluster`, `useRestoreCluster` from clusters API
  - `handleEnroll`: Step 2 now calls `promoteCluster.mutateAsync({ clusterId: cluster.id, personId: person.id })` instead of `rematchPerson.mutateAsync(person.id)`
  - 🚫 Noise button: enabled, wired to `handleIgnore` → `ignoreCluster.mutate(cluster.id)`, shows `…` spinner while pending
  - Added `showRestoreOnly` prop: when true, replaces action row with a single `↩ Restore` button
  - Added `onRestored` callback prop
- **`ClustersPage.tsx`:**
  - Added `useState` for `ignoredOpen` toggle
  - Added `useIgnoredClusters()` hook
  - Defensive filter: `activeClusters = clusters.filter(c => !c.ignored)`
  - Collapsed "Ignored (N)" section with rotating chevron button
  - Ignored grid renders `ClusterCard` with `showRestoreOnly` prop and inline `onRestored` invalidation callback

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all actions are fully wired. `listIgnoredClusters` falls back to empty array on 404/422 gracefully (same pattern as `listClusters`), so the Ignored section simply doesn't render until the API is available.

## Self-Check

**Result:** PASSED

| Check | Status |
|-------|--------|
| `services/web/src/types/api.ts` exists | ✅ FOUND |
| `services/web/src/api/clusters.ts` exists | ✅ FOUND |
| `services/web/src/components/ClusterCard.tsx` exists | ✅ FOUND |
| `services/web/src/pages/ClustersPage.tsx` exists | ✅ FOUND |
| Commit `83f2b39` (Task 1) exists | ✅ FOUND |
| Commit `eded1a8` (Task 2) exists | ✅ FOUND |
| TypeScript compiles clean (`tsc --noEmit`) | ✅ PASSED |
