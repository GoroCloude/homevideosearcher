# Requirements: HomeVideoSearcher v1.1

**Defined:** 2026-05-21
**Core Value:** Drill into any video to see all its detections and faces; remove unwanted videos cleanly

## v1.1 Requirements

### Video Detail Page

- [ ] **VDP-01**: Clicking the detections or faces count in the Videos grid navigates to `/videos/:id` — a dedicated video detail page
- [ ] **VDP-02**: Video detail page shows video metadata (filename, duration, status, ingestion date) and a "Play" button that opens the stream
- [ ] **VDP-03**: "Detections" tab shows a grid of frame thumbnails for all YOLO object detections in this video, each card showing class labels, confidence, and timestamp (`ts_ms`)
- [ ] **VDP-04**: "Faces" tab shows a grid of face thumbnails with person name (or "Unknown Cluster #N"), appearance count, and timestamp for each appearance
- [ ] **VDP-05**: "Faces" tab includes a timeline bar visualizing face appearances across the full video duration; clicking a mark on the timeline seeks to that timestamp in the video player
- [ ] **VDP-06**: Video detail page is reachable from a row click or dedicated icon on the Videos page

### Video Delete

- [ ] **DEL-01**: Delete button on the Videos page (per row) with a confirmation dialog before executing
- [ ] **DEL-02**: Delete button on the Video Detail page with a confirmation dialog; navigates back to Videos page after deletion
- [ ] **DEL-03**: Hard delete removes: `videos` DB row, all `frames` rows, all `detections` rows, all `face_detections` rows (including embeddings), the MinIO video file, and all MinIO frame thumbnail files
- [ ] **DEL-04**: After deletion, the video disappears from all pages (Videos grid, Search results, unknown cluster membership) — no orphaned DB rows or MinIO files
- [ ] **DEL-05**: Delete endpoint is protected by bearer token (`API_TOKEN`); unauthenticated requests return 401

## Future Requirements (Deferred from v1.0)

### Enhanced Clustering

- **CLUSTER-V2-01**: Manual cluster merge (two clusters → one person)
- **CLUSTER-V2-02**: Cluster split detection (same person aging over years → multiple clusters)
- **CLUSTER-V2-03**: Body re-identification (gait, clothing) for persons without visible face

### Notifications

- **NOTIF-V2-01**: Configurable per-person alert (e.g., "alert immediately if Uncle Tom appears, daily digest for others")
- **NOTIF-V2-02**: Push notification via PWA (no dependency on Telegram)

### Performance

- **PERF-V2-01**: OpenVINO export for YOLO11n (~2–3× CPU speedup, no accuracy loss)
- **PERF-V2-02**: Multi-video parallel ingestion (requires CPU headroom validation first)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time / live stream analysis | i5-6200 too slow for real-time; overnight batch is acceptable |
| Mobile app | Responsive web UI covers family use case |
| Multi-user auth | Single shared login sufficient for family |
| Audio analysis / speech recognition | Not relevant to security or family search |
| Cloud deployment | Self-hosted only by design |
| RTSP camera integration | Cameras write to disk; MinIO import is the integration point |
| Soft delete (hide only) | Hard delete is simpler and avoids storage waste |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| VDP-01 – VDP-06 | TBD | Pending |
| DEL-01 – DEL-05 | TBD | Pending |

**Coverage:**
- v1.1 requirements: 11 total
- Mapped to phases: TBD (roadmapper fills this)
- Unmapped: TBD

---
*Requirements defined: 2026-05-21*
