# Project State

## Current Status

**Phase:** 3 — Intelligence & Telegram Digest ✅ COMPLETE  
**Active plan:** —  
**Last action:** Phase 3 complete — HDBSCAN clustering engine, cluster management endpoints (ignore/restore/promote), Telegram sendMediaGroup digest, React UI promote/noise/restore wired, n8n 8am cron workflow.

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-16)

**Core value:** Automatically surface unknown faces from home camera footage and notify via daily Telegram digest  
**Current focus:** Phase 3 — Intelligence & Telegram Digest (complete)

- Phase 3 cluster management: POST /clusters/{id}/ignore sets ignored=true (reversible via DELETE); POST /clusters/{id}/promote bulk-updates face_detections.matched_person_id for all cluster members (no full-library rematch)
- Phase 3 Telegram digest: MinIO bytes fetched internally (not presigned URLs — Telegram servers can't reach Docker network); BytesIO.seek(0) required before InputMediaPhoto
- Phase 3 HDBSCAN: sklearn uses algorithm='kd_tree' (not 'boruvka_kdtree' which is standalone hdbscan package — ValueError at runtime); min_cluster_size=5, min_samples=2

## Next Step

v1.0 milestone archived and tagged. Run `/gsd-new-milestone` to start planning v2.0.

## Phase Snapshot

| Phase | Goal | Status |
|-------|------|--------|
| 1 — Foundation | Docker Compose stack ingests video, runs YOLO + InsightFace, writes to DB | ✅ Complete |
| 2 — Enrollment, Search & Automation | Enroll persons, search footage, n8n auto-trigger | ✅ Complete |
| 3 — Intelligence & Telegram Digest | HDBSCAN clustering, stable cluster UUIDs, Telegram album digest | ✅ Complete |
| 4 — Web UI | React UI for search, persons, clusters, settings | ✅ Complete |
| 5 — Video Upload UI | Upload videos from browser → MinIO → auto-ingest | ✅ Complete |

## Decisions

- frames_router registered without Depends(require_token) — presigned MinIO URLs are self-secured via HMAC+TTL
- Separate _public_client singleton for MINIO_PUBLIC_ENDPOINT ensures browser-resolvable presigned URLs
- GET /videos/{id}/stream-url returns JSON (not 302) for JS timestamp-seek use case
- Tailwind v3 pinned (3.4.19) with CommonJS config — v4 breaking changes avoided
- TanStack Query v5 object-form API throughout — no legacy positional args
- Split pending/applied filter state prevents live-refetch on every keystroke (Plan 02)
- FrameThumbnail uses <img> directly (no authFetch) because frames router is public (Plan 02)
- VideoModal reuses FrameThumbnail for consistency + skeleton in modal (Plan 02)
- React.Fragment key on sibling table rows (VideosPage) — prevents React key warnings (Plan 03)
- Native HTML5 FileReader for per-file preview thumbnails in EnrollmentDropzone (Plan 03)
- Toast system uses module-level singleton (not React context) so addToast() works from anywhere including outside components (Plan 04)
- transition-transform duration-200 used for toast animation (tailwindcss-animate plugin not installed) (Plan 04)
- skipLibCheck:true added to tsconfig.node.json to bypass Vite 8 Node type errors (Plan 04)
- vite-env.d.ts created to provide import.meta.env types missing from scaffold (Plan 04)

### Architecture constraints (non-negotiable)
- Two-tier face threshold (≥0.65 confident / 0.50–0.65 probable) must be encoded in schema/config from day 1 — cannot be retrofitted
- `face_detections.unknown_cluster_id` column and `unknown_clusters` table must be in initial schema — not a later migration
- HDBSCAN with `algorithm='kd_tree'` (sklearn name for boruvka_kdtree), `metric='euclidean'`, `min_cluster_size=5`, `min_samples=2` — not DBSCAN, not cosine precomputed matrix
- Stable cluster UUIDs required — cluster labels are never recreated, only updated incrementally
- pgvector HNSW index: m=32, ef_construction=128, ef_search=64 — not defaults (default m=16 is suboptimal for 512-dim)
- InsightFace buffalo_l model (~280 MB) baked into Docker image at build time — not downloaded at container startup
- YOLO and InsightFace load sequentially at startup (2-second delay between them) and run sequentially per frame — never parallel; memory constraint on 8 GB CPU-only host
- `POST /cluster/run` lives in `api` service — no separate batch-worker container
- Telegram digest uses `sendMediaGroup` (single album, ≤10 photos per message)
- Retroactive re-matching after enrollment = single SQL UPDATE, no re-ingest

### Key dependencies
- MinIO and n8n are external (already running) — not in docker-compose.yml
- Cloudflare Tunnel handles TLS — no HTTPS config needed in stack
- `insightface==0.7.3` requires Python 3.11 exactly (not 3.12+)
- `onnxruntime==1.26.0` CPU-only (not onnxruntime-gpu)
- `scikit-learn==1.8.0` — HDBSCAN is built-in since 1.3, no extra package

### Tooling
- `uv==0.11.14` as package manager in Dockerfiles (not pip)
- Tailwind CSS v3 pinned (v4 has breaking config changes)
- TanStack Query v5 API (`useQuery()` object-form only)
