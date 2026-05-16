# HomeVideoSearcher

## What This Is

A self-hosted home security and family archive system that indexes video footage from home cameras, detects objects (cars, people, animals), recognizes enrolled family faces, and groups unknown faces. Users receive a daily Telegram digest when unrecognized persons appear, and can browse/search footage through a web UI.

**Deployment:** Ubuntu server (shumov.eu infrastructure), Docker Compose, CPU-only inference (i5-6200, 8 GB RAM), exposed via Cloudflare Tunnel.

## Core Value

Automatically surface unknown faces from home camera footage and notify via Telegram — so the user knows when someone unfamiliar appeared, without having to watch hours of video.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Index video files from MinIO (with import path from disk/NAS)
- [ ] Detect objects per frame: person, car, animal (COCO subset)
- [ ] Detect and embed all faces per frame (known and unknown)
- [ ] Enroll known persons (family members) with reference images
- [ ] Cluster unknown faces across videos so recurring strangers are grouped
- [ ] Daily Telegram digest listing unknown face clusters that appeared in the past 24 h, with thumbnail
- [ ] Web UI: search by enrolled person, object class, date range; jump to video timestamp
- [ ] Web UI: manage enrolled persons (add, delete, upload reference images)
- [ ] Web UI: browse and label unknown face clusters (promote to known person)
- [ ] Single bearer-token auth; single-user / family use case

### Out of Scope

- Real-time / live stream analysis — overnight batch is sufficient; live processing needs GPU
- Mobile app — responsive web UI covers the use case
- Multi-user auth — single shared login is enough for family use
- Audio analysis / speech recognition — not relevant to security or family search
- Re-identification by body features (gait, clothing) — face is sufficient for v1
- Cloud deployment — self-hosted only

## Context

- **Existing infra:** MinIO (object storage), n8n (workflow orchestration), Cloudflare Tunnel — all already running
- **Video source:** Home camera recordings currently on disk/NAS; must be imported into MinIO before indexing
- **Hardware constraint:** i5-6200 CPU, 8 GB RAM, no GPU — CPU-only ONNX inference; tight on memory, sequential ML processing required
- **Primary trigger for notifications:** unknown/unfamiliar face in footage (security); secondary: finding family member appearances (archive)
- **Unknown faces:** must be clustered in v1 (user explicitly needs grouping to spot recurring strangers)
- **Processing latency:** overnight batch is acceptable; no real-time requirement

## Constraints

- **Hardware:** CPU-only, 8 GB RAM — limits batch size; YOLO and InsightFace must run sequentially per frame; swap file recommended
- **Tech stack:** Fixed (see requirements.md §3): Python 3.11, FastAPI, YOLOv8, InsightFace buffalo_l, PostgreSQL 16 + pgvector, React 18 + Vite + TypeScript, Tailwind CSS, Docker Compose
- **Embedding dimensions:** InsightFace ArcFace produces 512-dim embeddings; pgvector HNSW index required
- **Face match threshold:** ≥ 0.5 cosine similarity for confident match (buffalo_l)
- **Frame rate:** 1 fps extraction + scene-change frames; ~0.3–0.5× realtime processing expected

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Unknown face clustering in v1 | User explicitly wants to spot recurring strangers — store-individually approach doesn't serve the use case | — Pending |
| Telegram daily digest as core feature | Primary value is knowing when unknowns appear; not just a nice-to-have | — Pending |
| Overnight batch processing | i5-6200 is too slow for real-time; daily digest latency is acceptable | — Pending |
| InsightFace buffalo_l over buffalo_s | Higher accuracy for family recognition; false matches are annoying in personal use | — Pending |
| pgvector HNSW index for embeddings | Efficient approximate nearest neighbor for face matching at scale | — Pending |
| MinIO as primary video storage | Already running; integrates with n8n for trigger workflows | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-16 after initialization*
