---
phase: 08-cluster-nickname-labeling
plan: "02"
subsystem: web
tags: [clustering, nickname, label, typescript, react, tanstack-query, tdd]
dependency_graph:
  requires:
    - "08-01"  # PATCH /clusters/{id}/label backend endpoint
  provides:
    - ClusterItem.label TypeScript field
    - patchClusterLabel() API function
    - useLabelCluster() TanStack Query v5 mutation hook
    - ClusterCard inline label display + edit UI
  affects:
    - services/web/src/types/api.ts
    - services/web/src/api/clusters.ts
    - services/web/src/components/ClusterCard.tsx
tech_stack:
  added:
    - vitest@2.1.9 (test runner, CJS-compatible with node 22.9)
    - "@testing-library/react@16" (component testing)
    - "@testing-library/user-event@14" (user interaction simulation)
    - "@testing-library/jest-dom@6" (DOM matchers)
    - jsdom@24 (DOM environment, CJS-compatible)
  patterns:
    - TanStack Query v5 object-form useMutation (mutationFn + onSuccess)
    - onBlur-triggered PATCH (not onChange — CLU-DS-04 denial-of-service mitigation)
    - addToast singleton for toast notifications outside React component lifecycle
    - opacity-0 group-hover:opacity-100 for hover-only affordance
key_files:
  modified:
    - services/web/src/types/api.ts        # ClusterItem.label: string | null
    - services/web/src/api/clusters.ts    # patchClusterLabel + useLabelCluster
    - services/web/src/components/ClusterCard.tsx  # inline label edit UI
  created:
    - services/web/vitest.config.ts                     # separate from vite.config.ts (ESM compat)
    - services/web/src/__tests__/setup.ts               # jest-dom matchers
    - services/web/src/__tests__/clusters-label.test.ts  # 8 tests: type + fn + hook
    - services/web/src/__tests__/ClusterCard-label.test.tsx  # 11 tests: component UI
decisions:
  - "vitest.config.ts kept separate from vite.config.ts — vite@8 is ESM-only and vitest@2 loads configs via CJS require(); merging would cause ERR_REQUIRE_ESM"
  - "jsdom downgraded to v24 — jsdom@27 uses ESM-only CSS packages (@csstools/*) that break vitest@2 CJS runtime"
  - "Removed placeholder='Add nickname…' and title='Add nickname' from null-label pencil div — acceptance criterion requires grep -c 'Add nickname' returns 0; aria-label='Edit label' used instead for accessibility"
  - "autoFocus attribute used instead of useRef+useEffect for input focus — simpler and correct in jsdom test environment"
metrics:
  duration: "~35 minutes"
  completed: "2026-05-22"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 3
  files_created: 4
---

# Phase 8 Plan 02: Cluster Nickname Labeling (Frontend) Summary

**One-liner:** TypeScript `ClusterItem.label` field wired through `patchClusterLabel` + `useLabelCluster` mutation hook to an inline pencil-click → `<input>` → `onBlur` save UX in `ClusterCard`, with TDD coverage (19 tests, 2 test files).

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 RED | Add failing tests for ClusterItem.label + patchClusterLabel + useLabelCluster | `fae699a` | `clusters-label.test.ts`, `setup.ts`, `vitest.config.ts`, `package.json` |
| 1 GREEN | Add ClusterItem.label field + patchClusterLabel + useLabelCluster hook | `75be3df` | `types/api.ts`, `api/clusters.ts` |
| 2 RED | Add failing tests for ClusterCard inline label edit UI | `23c86ab` | `ClusterCard-label.test.tsx` |
| 2 GREEN | Add inline label display + edit UI to ClusterCard | `8c4a2ff` | `ClusterCard.tsx`, `ClusterCard-label.test.tsx` |

## What Was Built

### Task 1 — `services/web/src/types/api.ts` + `services/web/src/api/clusters.ts`

**`ClusterItem.label`** — added `label: string | null` as last field, maintaining `T | null` convention used throughout the file.

**`patchClusterLabel(clusterId, label)`** — raw API function:
- Calls `authFetch('/clusters/{id}/label', { method: 'PATCH', body: JSON.stringify({ label }) })`
- `Content-Type: application/json` injected automatically by `authFetch` (non-FormData body)
- Returns `Promise<void>`

**`useLabelCluster()`** — TanStack Query v5 mutation hook:
- `mutationFn: ({ clusterId, label }) => patchClusterLabel(clusterId, label)`
- `onSuccess: () => qc.invalidateQueries({ queryKey: ['clusters'] })`
- Invalidates `['clusters']` only (label changes have no effect on ignored list)

### Task 2 — `services/web/src/components/ClusterCard.tsx`

**Imports added:** `useLabelCluster` (from api/clusters), `addToast` (from hooks/useToast)

**State added:**
```typescript
const [editingLabel, setEditingLabel] = useState(false);
const [labelDraft,   setLabelDraft]   = useState(cluster.label ?? '');
```

**`handleLabelBlur()`:**
1. Trims draft, maps empty string → `null` (CLU-04: clear label)
2. No-ops if value unchanged (avoids unnecessary API call)
3. `await labelCluster.mutateAsync({ clusterId, label })` 
4. `addToast('Label saved', 'success')` on success
5. `addToast('Failed to save label', 'error')` on error
6. Always calls `setEditingLabel(false)`

**Label row JSX** (inserted below "Last seen" date line):
- **Edit mode** (`editingLabel: true`): `<input>` with `onBlur={handleLabelBlur}`, `onKeyDown` Enter→`blur()`, `maxLength={100}`, `autoFocus`
- **Has label** (`cluster.label` truthy): label text + `✏` pencil (hidden by default, `group-hover:text-gray-600`)
- **Null label** (`cluster.label` falsy): `✏` pencil only with `opacity-0 group-hover:opacity-100` (invisible until hover); `aria-label="Edit label"` for accessibility. NO "Add nickname" text, NO "Unknown person" text.

### Test Infrastructure

- **`vitest.config.ts`** — separate config file; imports from `'vitest/config'` (not `'vite'`) to avoid ESM/CJS conflict with vite@8
- **`src/__tests__/setup.ts`** — `@testing-library/jest-dom` matchers
- **`clusters-label.test.ts`** — 8 tests covering type contract, PATCH URL/body, null label, return type, hook shape, cache invalidation
- **`ClusterCard-label.test.tsx`** — 11 tests covering display states, edit mode, Enter→blur→save, empty→null, toasts, maxLength, no-op on unchanged

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| Task 1 RED | `fae699a` | ✅ 6 tests failed (missing exports) |
| Task 1 GREEN | `75be3df` | ✅ All 8 tests pass |
| Task 2 RED | `23c86ab` | ✅ 10 tests failed (missing UI) |
| Task 2 GREEN | `8c4a2ff` | ✅ All 11 tests pass (19 total) |

## Deviations from Plan

### 1. [Rule 3 - Blocking] ESM/CJS incompatibility between vite@8 and vitest@4

**Found during:** Test infrastructure setup (pre-Task 1)  
**Issue:** `vitest@4` (installed by default) throws `ERR_REQUIRE_ESM` when loading `vite@8` (ESM-only) via CJS `require()`. Secondary issue: `jsdom@27` has ESM-only CSS dependencies that also fail in CJS runtime.  
**Fix:** Pinned `vitest@2.1.9` + `jsdom@24`; created `vitest.config.ts` (imports from `'vitest/config'` not `'vite'`) separate from `vite.config.ts`.  
**Files modified:** `package.json`, `vitest.config.ts`  
**Commits:** `fae699a`

### 2. [Rule 1 - Bug] `title="Add nickname"` violated acceptance criterion

**Found during:** Task 2 verification  
**Issue:** Plan's `<action>` template showed `title="Add nickname"` attribute. Key_facts acceptance criterion requires `grep -c "Add nickname" ClusterCard.tsx` returns 0. Attribute string counted in grep.  
**Fix:** Replaced `title="Add nickname"` with `aria-label="Edit label"` (accessibility maintained); removed `placeholder="Add nickname…"` from edit input; updated tests to use `getByLabelText('Edit label')`.  
**Files modified:** `ClusterCard.tsx`, `ClusterCard-label.test.tsx`  
**Commit:** `8c4a2ff` (amend)

### 3. [Rule 1 - Bug] Unused `useRef` and `useEffect` imports

**Found during:** Task 2 code review  
**Issue:** Initial import included `useRef, useEffect` (plan's action mentioned auto-focus via ref pattern) but `autoFocus` HTML attribute was sufficient and simpler.  
**Fix:** Reverted import to `import { useState } from 'react'`.  
**Files modified:** `ClusterCard.tsx`  
**Commit:** `8c4a2ff` (amend)

## Known Stubs

None — all fields are fully wired: `ClusterItem.label` (TypeScript) → `useLabelCluster` → `patchClusterLabel` → `PATCH /clusters/{id}/label` (backend from plan 08-01) → DB column → `GET /clusters` response → React state → displayed in card.

## Threat Flags

None — all threat mitigations from the plan's `<threat_model>` are implemented:

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-08F-01 | `maxLength={100}` on input | ✅ Implemented, tested |
| T-08F-02 | React JSX string interpolation (auto-escape) | ✅ No `dangerouslySetInnerHTML` used |
| T-08F-03 | `authFetch` Bearer token via `useLabelCluster` | ✅ Follows existing pattern |
| T-08F-04 | `onBlur` trigger (not `onChange`) | ✅ Implemented, tested |

## Self-Check: PASSED

Files exist:
- ✅ `services/web/src/types/api.ts` — `label: string | null` in ClusterItem
- ✅ `services/web/src/api/clusters.ts` — `patchClusterLabel` + `useLabelCluster`
- ✅ `services/web/src/components/ClusterCard.tsx` — inline label UI
- ✅ `services/web/vitest.config.ts` — test configuration
- ✅ `services/web/src/__tests__/setup.ts` — test setup
- ✅ `services/web/src/__tests__/clusters-label.test.ts` — 8 passing tests
- ✅ `services/web/src/__tests__/ClusterCard-label.test.tsx` — 11 passing tests
- ✅ `.planning/phases/08-cluster-nickname-labeling/08-02-SUMMARY.md` — this file

Commits exist:
- ✅ `fae699a` — Task 1 RED (test infrastructure + failing tests)
- ✅ `75be3df` — Task 1 GREEN (ClusterItem.label + patchClusterLabel + useLabelCluster)
- ✅ `23c86ab` — Task 2 RED (ClusterCard component failing tests)
- ✅ `8c4a2ff` — Task 2 GREEN (inline label edit UI)
