---
phase: 08-cluster-nickname-labeling
plan: "01"
subsystem: api
tags: [clustering, nickname, label, digest, telegram]
dependency_graph:
  requires: []
  provides:
    - PATCH /clusters/{id}/label endpoint
    - ClusterResponse.label field
    - GET /clusters includes label column
    - digest caption uses cluster label with fallback
  affects:
    - services/api/app/clustering.py
    - services/api/app/digest.py
tech_stack:
  added: []
  patterns:
    - asyncpg pool acquire + execute + UPDATE 0 guard (existing pattern, reused)
    - Pydantic BaseModel for PATCH request body
    - SQL parameterized query ($1, $2) via asyncpg
key_files:
  modified:
    - services/api/app/clustering.py
    - services/api/app/digest.py
decisions:
  - Empty string label body value normalised to None at API layer (not written to DB as empty string)
  - Label validation (max 100 chars) applied after strip to avoid counting leading/trailing whitespace
  - PATCH endpoint inherits require_token auth automatically from clustering router registration — no per-endpoint Depends decorator added
metrics:
  duration: "~15 minutes"
  completed: "2026-05-22"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 8 Plan 01: Cluster Nickname Labeling (Backend) Summary

**One-liner:** PATCH endpoint writes freeform nicknames to `unknown_clusters.label`; `ClusterResponse` and digest caption consume the field with `"Unknown person"` fallback.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Add PATCH endpoint + ClusterLabelRequest + ClusterResponse.label + uc.label in GET | `4d0961d` | `services/api/app/clustering.py` |
| 2 | Update digest.py caption to use cluster label with fallback | `45e6c87` | `services/api/app/digest.py` |

## What Was Built

### Task 1 — `services/api/app/clustering.py`

- **`ClusterLabelRequest`** Pydantic model added: `label: Optional[str] = None`
- **`ClusterResponse.label`** field added: `label: Optional[str] = None` (after `ignored: bool`)
- **`GET /clusters` SELECT** updated to include `uc.label`; constructor now passes `label=r["label"]`
- **`PATCH /clusters/{cluster_id}/label`** (`set_cluster_label`) endpoint added:
  - Strips surrounding whitespace: `body.label.strip() if body.label else None`
  - Empty string → `None` in DB (clears label)
  - Rejects labels > 100 chars with HTTP 422
  - Returns HTTP 404 if cluster UUID not found (`UPDATE 0` guard)
  - Returns `{"id": str, "label": str | None}` on success

### Task 2 — `services/api/app/digest.py`

- **SELECT** updated to include `uc.label` alongside the existing columns
- **Caption** replaced:
  - Before: `caption = f"Unknown person — seen {count}×, {first} → {last}"`
  - After: `name = cluster["label"] or "Unknown person"` / `caption = f"{name} — seen {count}×, {first} → {last}"`
- Handles both SQL `NULL` (Python `None`) and empty string as fallback to "Unknown person"

## Deviations from Plan

### Minor — Plan criterion discrepancy (not a code issue)

**Found during:** Task 1 verification  
**Issue:** The plan's success criterion stated `grep -c "uc\.label" services/api/app/clustering.py ≥ 2` and the acceptance criteria comment said "(SELECT + constructor)". However, `uc` is a SQL table alias — it only exists inside the SQL string. The Python constructor correctly accesses the column as `r["label"]` (asyncpg `Record` key), not `uc.label`. The implementation is correct; the plan's grep pattern was overly broad.  
**Actual count:** 1 occurrence of `uc.label` in `clustering.py` (in the SQL SELECT). All other criteria met exactly.  
**Impact:** None — functionality is complete and correct.

## Known Stubs

None — all fields are fully wired from DB column to API response and digest caption.

## Threat Flags

None — no new network surface or trust boundaries introduced beyond what the plan's threat model covered.

## Self-Check: PASSED

Files exist:
- ✅ `services/api/app/clustering.py` — modified
- ✅ `services/api/app/digest.py` — modified
- ✅ `.planning/phases/08-cluster-nickname-labeling/08-01-SUMMARY.md` — this file

Commits exist:
- ✅ `4d0961d` — Task 1 (clustering.py)
- ✅ `45e6c87` — Task 2 (digest.py)
