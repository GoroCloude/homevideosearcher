# Requirements: HomeVideoSearcher v2.0

**Milestone:** v2.0 — Smart Labels, Person Pages & Auto-Ingest  
**Status:** Active  
**Created:** 2026-05-22

---

## v1 Requirements (this milestone)

### Cluster Nickname Labeling

- [ ] **CLU-01**: User can type a freeform nickname on any cluster card; saving calls `PATCH /clusters/{id}/label` and the name persists on the `unknown_clusters.label` column
- [ ] **CLU-02**: Cluster nickname (when set) appears on the cluster card below the date range; blank/null shows nothing (not "Unknown person")
- [ ] **CLU-03**: Telegram digest caption uses the cluster nickname when present (`"{nickname}" seen {count} times`); falls back to "Unknown person" when null
- [ ] **CLU-04**: User can clear a cluster nickname (empty input → null); card reverts to unlabeled display

### Person Appearance Page

- [ ] **PAP-01**: Clicking a known person on the People page navigates to `/people/:id`
- [ ] **PAP-02**: Person detail page lists all videos they appear in, each with a face thumbnail, first timestamp, and appearance count; sorted newest-first
- [ ] **PAP-03**: Person detail page shows a chronological timeline/calendar of appearance dates across all videos
- [ ] **PAP-04**: Clicking a video appearance navigates to `/videos/:id?t={ts_ms}` — the video detail page at that timestamp
- [ ] **PAP-05**: VideoDetailPage reads the `?t=ts_ms` URL query param on mount and seeks the video player to that timestamp

### Watch-Folder Auto-Ingest

- [ ] **AUTO-01**: A `watcher` Docker Compose service monitors a configured local folder; new video files are automatically uploaded to MinIO and ingested through the full pipeline (YOLO + InsightFace + face matching)
- [ ] **AUTO-02**: Watcher waits for a file write to fully complete before triggering upload (`on_closed` watchdog event or size-stability polling fallback)
- [ ] **AUTO-03**: On container start, watcher scans the folder and queues any eligible files not yet ingested (handles files dropped during service downtime)
- [ ] **AUTO-04**: Only `.mp4`, `.mov`, `.avi`, `.mkv` files trigger the pipeline; all other file types are silently ignored
- [ ] **AUTO-05**: Ingestion worker serialises ML pipeline execution with a `Semaphore(1)` to prevent concurrent YOLO+InsightFace runs from exhausting the 8 GB RAM host
- [ ] **AUTO-06**: Watcher emits one structured log line per file state transition: `DETECTED | STABLE | UPLOADING | QUEUED | SKIPPED | ERROR`
- [ ] **AUTO-07**: `WATCH_USE_POLLING=true` environment variable switches the watcher to polling mode for NFS/CIFS mounts where Linux inotify is unavailable

---

## Future Requirements (deferred)

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| Calendar heat-map widget on person page | v2.1+ | Nice-to-have differentiator; table-stakes done in v2.0 with timeline list |
| Date-range filter on person appearance page | v2.1+ | Low priority for current video volume |
| Natural language search | v3.0 | Requires LLM integration research; significant new architecture |
| Per-person Telegram alerts | v2.1+ | Real-time alerting; separate from daily digest feature |
| Stranger alert (new unknown face notification) | v2.1+ | Requires real-time or near-real-time processing loop |
| Stats/insights dashboard | v3.0 | Lower value than person-centric features at current video volume |
| Cluster merge/split | v2.1+ | Requires HDBSCAN re-run coordination; deferred to avoid ML scope |

---

## Out of Scope

| Item | Reason |
|------|--------|
| Label → enrolled person conversion | CLU features explicitly do NOT enroll; `known_persons` only created via the enrollment flow |
| Cluster merge on label collision | Two clusters with the same label are not the same person automatically |
| Real-time ingestion from live camera streams | CPU-only hardware cannot sustain real-time; watch-folder is batch-on-arrival not streaming |
| Watch-folder UI page in the web app | Ingested files appear in the existing Videos list; no separate management UI needed |
| Multi-folder watching | Single folder is sufficient for the use case; add as config extension later if needed |
| Watch-folder auth (from watcher to ingestion-worker) | `/ingest` endpoint has no auth middleware — internal Docker network only |
| Body re-identification | Face is sufficient for family recognition use case |

---

## Traceability

| Requirement | Phase | Plans |
|-------------|-------|-------|
| CLU-01 | Phase 8 | TBD |
| CLU-02 | Phase 8 | TBD |
| CLU-03 | Phase 8 | TBD |
| CLU-04 | Phase 8 | TBD |
| PAP-01 | Phase 9 | TBD |
| PAP-02 | Phase 9 | TBD |
| PAP-03 | Phase 9 | TBD |
| PAP-04 | Phase 9 | TBD |
| PAP-05 | Phase 9 | TBD |
| AUTO-01 | Phase 10 | TBD |
| AUTO-02 | Phase 10 | TBD |
| AUTO-03 | Phase 10 | TBD |
| AUTO-04 | Phase 10 | TBD |
| AUTO-05 | Phase 10 | TBD |
| AUTO-06 | Phase 10 | TBD |
| AUTO-07 | Phase 10 | TBD |
