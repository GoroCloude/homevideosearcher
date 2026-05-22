# Roadmap: HomeVideoSearcher

**Current milestone:** v1.1 Video Detail & Delete  
**Last shipped:** [v1.0 MVP](.planning/milestones/v1.0-ROADMAP.md) — 5 phases, 14 plans, 99 commits — 2026-05-21

---

## ✅ v1.0 MVP — SHIPPED 2026-05-21

> Full self-hosted home security and family archive system: video ingestion, YOLO object detection, InsightFace face recognition, HDBSCAN unknown face clustering, Telegram digest, React web UI, and direct video upload. Deployed on i5-6200 Ubuntu server via Cloudflare Tunnel.
>
> **Full archive:** [.planning/milestones/v1.0-ROADMAP.md](.planning/milestones/v1.0-ROADMAP.md)

---

## v1.1 Video Detail & Delete

**Target:** Drill into any video to see all detections and faces; hard-delete unwanted videos.
**Milestone:** v1.1

---

### Phase 6: Video Detail & Delete API

**Goal:** Expose API endpoints that deliver per-video metadata, detections, and faces, plus a hard-delete endpoint with full DB + MinIO cascade cleanup protected by bearer-token auth.

**Requirements covered:** DEL-03, DEL-05

**Plans:** 2 plans

Plans:
- [x] 06-01-PLAN.md — Read endpoints: GET /videos/{id}/detail, GET /videos/{id}/detections, GET /videos/{id}/faces
- [x] 06-02-PLAN.md — Hard delete: DELETE /videos/{id} with DB cascade + MinIO cleanup + auth verification

**Done when:**
- [x] `GET /videos/{id}` returns filename, duration, status, ingestion date, and a stream URL
- [x] `GET /videos/{id}/detections` returns all YOLO detection records for the video with frame thumbnail URL, class label, confidence, and `ts_ms` timestamp
- [x] `GET /videos/{id}/faces` returns all face detection records with person name (or "Unknown Cluster #N"), appearance count, and `ts_ms` timestamp
- [x] `DELETE /videos/{id}` removes the `videos` row, all associated `frames`, `detections`, and `face_detections` rows, the MinIO video file, and all MinIO frame thumbnail files — confirmed by DB count and MinIO list returning zero artifacts
- [ ] `DELETE /videos/{id}` without a valid bearer token returns HTTP 401

**UI hint**: no

---

### Phase 7: Video Detail Page + Delete UI

**Goal:** Users can open any video's detail page to browse detections and faces with a timeline, watch the video, and permanently delete it from either the Videos grid or the detail page.

**Requirements covered:** VDP-01, VDP-02, VDP-03, VDP-04, VDP-05, VDP-06, DEL-01, DEL-02, DEL-04

**Plans:** TBD

**Done when:**
- [ ] Clicking a detection count, face count cell, or the row itself on the Videos page navigates to `/videos/:id`; a dedicated row icon also links to the detail page
- [ ] The detail page displays video metadata (filename, duration, status, ingestion date) and a Play button that opens the video stream in-page
- [ ] The "Detections" tab renders a responsive grid of frame thumbnails; each card shows class label, confidence, and timestamp
- [ ] The "Faces" tab renders a grid of face thumbnails each showing person name or "Unknown Cluster #N" and timestamp, plus a timeline bar where clicking any mark seeks the video player to that timestamp
- [ ] A Delete button on the Videos page row (confirmation dialog) and a Delete button on the detail page (confirmation dialog → navigate back to Videos) both remove the video; it disappears from the Videos grid, Search results, and cluster membership immediately with no stale data visible

**UI hint**: yes

---

## Progress

| Phase | Plans | Status | Completed |
|-------|-------|--------|-----------|
| 6 — Video Detail & Delete API | 2 | 🔄 Checkpoint | 2/2 plans (human verify pending) |
| 7 — Video Detail Page + Delete UI | TBD | ⏳ Pending | — |

---

## v2.0 — TBD

> Next major milestone not yet planned. Run `/gsd-new-milestone` to define goals and requirements.

---

*Roadmap created: 2026-05-16 | v1.0 archived: 2026-05-21 | v1.1 added: 2026-05-21*
