# Roadmap: HomeVideoSearcher

**Current milestone:** v2.0 Smart Labels, Person Pages & Auto-Ingest  
**Last shipped:** [v1.1 Video Detail & Delete](.planning/milestones/v1.1-ROADMAP.md) — 2 phases, 5 plans, 20 commits — 2026-05-22

---

## ✅ v1.0 MVP — SHIPPED 2026-05-21

> Full self-hosted home security and family archive system: video ingestion, YOLO object detection, InsightFace face recognition, HDBSCAN unknown face clustering, Telegram digest, React web UI, and direct video upload. Deployed on i5-6200 Ubuntu server via Cloudflare Tunnel.
>
> **Full archive:** [.planning/milestones/v1.0-ROADMAP.md](.planning/milestones/v1.0-ROADMAP.md)

---

## ✅ v1.1 Video Detail & Delete — SHIPPED 2026-05-22

> Drill into any video: Detections tab (YOLO thumbnails), Faces tab (face grid + timeline seek), in-page video player, hard delete with full DB + MinIO cascade. 2 phases, 5 plans, 20 commits.
>
> **Full archive:** [.planning/milestones/v1.1-ROADMAP.md](.planning/milestones/v1.1-ROADMAP.md)

---

## v2.0 — Smart Labels, Person Pages & Auto-Ingest

> Give unknown clusters nicknames, browse every video a known person appears in, and drop new footage into a watch folder for zero-touch ingest.

### Phases

- [ ] **Phase 8: Cluster Nickname Labeling** — Inline label on cluster cards; persists to DB; surfaces in Telegram digest
- [ ] **Phase 9: Person Appearance Page** — Click a person → see every video they appear in with timestamps and thumbnails
- [ ] **Phase 10: Watch-Folder Auto-Ingest** — Daemon watches a local folder; new files are uploaded to MinIO and ingested automatically

---

### Phase Details

#### Phase 8: Cluster Nickname Labeling
**Goal**: Users can attach a freeform nickname to any cluster card; the name persists and appears in the Telegram digest  
**Depends on**: Nothing (extends existing clusters feature)  
**Requirements**: CLU-01, CLU-02, CLU-03, CLU-04  
**Success Criteria** (what must be TRUE):
  1. User types a nickname on a cluster card, saves it, and the label is visible the next time the Clusters page loads
  2. A cluster with no nickname shows no placeholder text — the card is identical to its pre-label state
  3. User clears an existing nickname (empty input) and the card reverts to unlabeled display
  4. Next Telegram digest caption reads `"{nickname}" seen N times` for labeled clusters; unlabeled clusters still read `"Unknown person" seen N times`
**Plans**: 2 plans
- [ ] 08-01-PLAN.md — Backend: PATCH /clusters/{id}/label + ClusterResponse.label + digest caption
- [ ] 08-02-PLAN.md — Frontend: ClusterItem type + patchClusterLabel + useLabelCluster + ClusterCard inline edit
**UI hint**: yes

---

#### Phase 9: Person Appearance Page
**Goal**: Clicking a known person shows every video they appear in with face thumbnails, timestamps, and an appearance timeline  
**Depends on**: Phase 8 (none — independent; phases 8 and 9 can be built in parallel)  
**Requirements**: PAP-01, PAP-02, PAP-03, PAP-04, PAP-05  
**Success Criteria** (what must be TRUE):
  1. Clicking any person card on the People page navigates to `/people/:id` without a full page reload
  2. The person detail page lists all videos they appear in, newest first, each showing a face thumbnail, the first timestamp they appear, and how many times they appear in that video
  3. Clicking a video row on the person page opens the video detail page seeked to the correct timestamp
  4. Visiting `/people/:id` for a non-existent person ID shows a 404 state; visiting for a person with no matched detections shows an empty state
  5. Pasting or bookmarking a URL like `/videos/:id?t=12345` opens the video detail page with the player seeked to that timestamp on mount
**Plans**: TBD  
**UI hint**: yes

---

#### Phase 10: Watch-Folder Auto-Ingest
**Goal**: A new Docker Compose service monitors a configured folder; video files dropped there are automatically uploaded to MinIO and run through the full ingestion pipeline with zero manual steps  
**Depends on**: Phase 8, Phase 9 (independent; can start after those phases are stable)  
**Requirements**: AUTO-01, AUTO-02, AUTO-03, AUTO-04, AUTO-05, AUTO-06, AUTO-07  
**Success Criteria** (what must be TRUE):
  1. Copying a `.mp4` file into the watched folder causes it to appear in the Videos list within the time it takes the ingestion pipeline to run — with no manual upload or API call by the operator
  2. Dropping a non-video file (e.g. `.txt`, `.jpg`) into the watched folder produces no ingestion attempt and no error visible to the user
  3. Stopping and restarting the watcher container while files are in the folder results in all un-ingested files being picked up on startup — nothing is silently lost
  4. Two video files arriving at nearly the same time are processed sequentially, not concurrently; the host never OOM-kills the ingestion worker
  5. Setting `WATCH_USE_POLLING=true` in the environment enables polling-based watching, and the same ingest behavior is observed on NFS/CIFS mounts where inotify is unavailable
  6. Each file transition (`DETECTED`, `STABLE`, `UPLOADING`, `QUEUED`, `SKIPPED`, `ERROR`) appears as a structured log line in `docker-compose logs watcher`
**Plans**: TBD

---

### Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 8. Cluster Nickname Labeling | 0/2 | Not started | — |
| 9. Person Appearance Page | 0/? | Not started | — |
| 10. Watch-Folder Auto-Ingest | 0/? | Not started | — |

---

*Roadmap created: 2026-05-16 | v1.0 archived: 2026-05-21 | v1.1 added: 2026-05-21 | v2.0 added: 2026-05-22*
