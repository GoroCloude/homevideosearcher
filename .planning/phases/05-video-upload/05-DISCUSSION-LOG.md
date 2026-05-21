# Phase 5: Video Upload UI — Discussion Log

**Date:** 2026-05-27
**Areas discussed:** 4 of 4

---

## Area 1: Queue failure handling

| Question | Options presented | Decision |
|----------|------------------|----------|
| What happens to remaining files when 1 fails? | Continue / Stop / Retry once | **Continue** — show error toast, upload next file |
| Button state after queue finishes with partial failure? | Reset / Show summary / Agent decides | **Show summary** — "2/3 uploaded" in button |

---

## Area 2: MinIO CORS setup

| Question | Options presented | Decision |
|----------|------------------|----------|
| Where to document CORS config? | Shell script / README / docker-compose | **docker-compose** (initial choice) |
| Clarification: MinIO is external, not in docker-compose | scripts/setup-minio-cors.sh / README / Docker init service | **Shell script** `scripts/setup-minio-cors.sh` with mc CLI |

---

## Area 3: Component breakdown

| Question | Options presented | Decision |
|----------|------------------|----------|
| Standalone component vs inline in VideosPage? | New VideoUploadButton.tsx / Inline in VideosPage | **New component** `VideoUploadButton.tsx` |
| How many plan files? | One plan / Two plans | **One plan** — 05-01-PLAN.md covers everything |

---

## Area 4: Progress indicator design

| Question | Options presented | Decision |
|----------|------------------|----------|
| Where to show upload % | Button text only / Progress bar / Both | **Progress bar** |
| Multi-file progress behavior | Per-file reset / Overall queue / Agent decides | **Overall queue** — total bytes across all files |
| Progress bar position on page | Below header / Inside button area / Agent decides | **Below header** — thin bar between header row and table |

---

## Deferred Ideas

- Drag-and-drop zone — out of scope per SPEC.md
- Per-file progress bars — overall progress chosen instead
- Upload history/audit log — out of scope per SPEC.md
