# HomeVideoSearcher

## Current Milestone: v2.0 Smart Labels, Person Pages & Auto-Ingest

**Goal:** Make the system smarter about recurring people and require zero manual upload steps.

**Target features:**
- **Cluster nicknames** — Give unknown face clusters a freeform label ("delivery guy", "neighbor") that shows in the UI without enrolling them as a full known person
- **Person appearance page** — Click a known person → all videos they appear in with timestamps/thumbnails + chronological appearance timeline
- **Watch-folder auto-ingest** — Daemon watches a local folder; new files immediately upload to MinIO and trigger the ingestion pipeline

---

<details>
<summary>v1.1 — Video Detail &amp; Delete (archived 2026-05-22)</summary>

**Goal:** Drill into any video to see all its detections and faces, and remove unwanted videos cleanly from the system.

**Shipped:** 2026-05-22 | **Full archive:** [.planning/milestones/v1.1-ROADMAP.md](.planning/milestones/v1.1-ROADMAP.md)

</details>

---

## Current State (v1.1 — Shipped 2026-05-22)

**v1.1 is live.** All 7 phases complete across v1.0 + v1.1. Deployed on Ubuntu homeserver (i5-6200, 8 GB RAM, CPU-only), exposed via Cloudflare Tunnel at `homevideosearcher.shumov.eu`.

**What's running:**
- Video ingestion pipeline (FFmpeg + YOLO + InsightFace, all CPU-only)
- Face enrollment and pgvector similarity search
- HDBSCAN nightly clustering of unknown faces
- Telegram digest via `@gorohomealert_bot` — sends cluster photo albums
- React web UI: search, people, clusters, video upload, video detail page with detection/face tabs + timeline
- Per-video hard delete (DB cascade + MinIO cleanup)
- n8n 8am daily cron: cluster/run → digest/send

---

## What This Is

A self-hosted home security and family archive system that indexes video footage from home cameras, detects objects (cars, people, animals), recognizes enrolled family faces, and groups unknown faces. Users receive a daily Telegram digest when unrecognized persons appear, and can browse/search footage through a web UI.

**Deployment:** Ubuntu server (shumov.eu infrastructure), Docker Compose, CPU-only inference (i5-6200, 8 GB RAM), exposed via Cloudflare Tunnel.

## Core Value

Automatically surface unknown faces from home camera footage and notify via Telegram — so the user knows when someone unfamiliar appeared, without having to watch hours of video.

## Requirements

### Validated (v1.0)

- [x] Index video files from MinIO (with import path from disk/NAS)
- [x] Detect objects per frame: person, car, animal (COCO subset)
- [x] Detect and embed all faces per frame (known and unknown)
- [x] Enroll known persons (family members) with reference images
- [x] Cluster unknown faces across videos so recurring strangers are grouped
- [x] Daily Telegram digest listing unknown face clusters with thumbnails
- [x] Web UI: search by enrolled person, object class, date range; jump to video timestamp
- [x] Web UI: manage enrolled persons (add, delete, upload reference images)
- [x] Web UI: browse and label unknown face clusters (promote to known person)
- [x] Web UI: upload video files directly from browser
- [x] Single bearer-token auth; single-user / family use case

### Out of Scope

- Real-time / live stream analysis — overnight batch is sufficient; live processing needs GPU
- Mobile app — responsive web UI covers the use case
- Multi-user auth — single shared login is enough for family use
- Audio analysis / speech recognition — not relevant to security or family search
- Re-identification by body features (gait, clothing) — face is sufficient for v1
- Cloud deployment — self-hosted only

## Context

- **Existing infra:** MinIO (object storage), n8n (workflow orchestration), Cloudflare Tunnel — all already running
- **Video source:** Home camera recordings currently on disk/NAS; imported into MinIO before indexing
- **Hardware constraint:** i5-6200 CPU, 8 GB RAM, no GPU — CPU-only ONNX inference; tight on memory, sequential ML processing required
- **Processing latency:** overnight batch is acceptable; no real-time requirement
- **Telegram bot:** `@gorohomealert_bot`, chat ID `8327914287`

## Constraints

- **Hardware:** CPU-only, 8 GB RAM — limits batch size; YOLO and InsightFace must run sequentially per frame; swap file recommended
- **Tech stack:** Python 3.11, FastAPI, YOLOv8, InsightFace buffalo_l, PostgreSQL 16 + pgvector, React 18 + Vite + TypeScript, Tailwind CSS v3, Docker Compose
- **Embedding dimensions:** InsightFace ArcFace produces 512-dim embeddings; pgvector HNSW index required
- **Frame rate:** 1 fps extraction + scene-change frames

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Unknown face clustering in v1 | User explicitly wants to spot recurring strangers | ✓ Validated — 5 clusters found in first run |
| Telegram daily digest as core feature | Primary value is knowing when unknowns appear | ✓ Validated — working live |
| Overnight batch processing | i5-6200 is too slow for real-time; daily digest latency is acceptable | ✓ Validated |
| InsightFace buffalo_l over buffalo_s | Higher accuracy for family recognition | ✓ Validated |
| pgvector HNSW index for embeddings | Efficient approximate nearest neighbor for face matching | ✓ Validated |
| MinIO as primary video storage | Already running; integrates with n8n for trigger workflows | ✓ Validated |
| HDBSCAN `algorithm='kd_tree'` (sklearn) | sklearn uses different param name than standalone hdbscan package | ✓ Corrected during Phase 3 |
| `POST /clusters/{id}/promote` (not rematch) | Rematch requires existing embeddings; new persons don't have any | ✓ Fixed Phase 3 ClusterCard flow |
| Separate `_public_client` for presigned URLs | Internal Docker hostname not browser-resolvable | ✓ Good |
| Module-level toast singleton (not React context) | `addToast()` must work outside components | ✓ Good |

## Evolution

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-22 — v2.0 started*
