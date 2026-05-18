---
phase: 04-web-ui
plan: "01"
subsystem: api-fixes + web-scaffold
tags: [react, vite, tailwind, tanstack-query, fastapi, minio, typescript]
dependency_graph:
  requires: []
  provides:
    - frames-router-public
    - minio-public-endpoint
    - get-videos-endpoint
    - stream-url-endpoint
    - react-scaffold
    - api-hook-layer
    - multi-stage-dockerfile
  affects:
    - services/api
    - services/web
tech_stack:
  added:
    - React 18.3.1
    - Vite 8.0.13
    - TanStack Query v5.100.10
    - react-router-dom 6.30.1
    - Tailwind CSS v3.4.19
    - TypeScript 5.9.3
  patterns:
    - localStorage-backed settings context
    - TanStack Query v5 object-form hooks
    - Multi-stage Docker build (node:22-alpine → nginx:1.27-alpine)
    - Public MinIO client for browser-resolvable presigned URLs
key_files:
  created:
    - services/web/package.json
    - services/web/vite.config.ts
    - services/web/tailwind.config.js
    - services/web/postcss.config.js
    - services/web/tsconfig.json
    - services/web/tsconfig.node.json
    - services/web/tsconfig.app.json
    - services/web/index.html
    - services/web/src/index.css
    - services/web/src/main.tsx
    - services/web/src/App.tsx
    - services/web/src/types/api.ts
    - services/web/src/context/SettingsContext.tsx
    - services/web/src/hooks/useApiToken.ts
    - services/web/src/pages/SearchPage.tsx
    - services/web/src/pages/VideosPage.tsx
    - services/web/src/pages/PeoplePage.tsx
    - services/web/src/pages/ClustersPage.tsx
    - services/web/src/pages/SettingsPage.tsx
    - services/web/src/components/Layout.tsx
    - services/web/src/api/client.ts
    - services/web/src/api/persons.ts
    - services/web/src/api/search.ts
    - services/web/src/api/videos.ts
    - services/web/src/api/clusters.ts
    - services/web/src/api/frames.ts
    - services/web/package-lock.json
  modified:
    - services/api/app/main.py
    - services/api/app/config.py
    - services/api/app/storage.py
    - services/api/app/videos.py
    - services/web/Dockerfile
    - docker-compose.yml
    - .env.example
decisions:
  - "frames_router registered without Depends(require_token) — presigned MinIO URLs are self-secured via HMAC+TTL"
  - "Separate _public_client singleton for MINIO_PUBLIC_ENDPOINT ensures browser-resolvable presigned URLs"
  - "GET /videos/{id}/stream-url returns JSON (not 302) for JS timestamp-seek use case"
  - "Tailwind v3 pinned (3.4.19) with CommonJS config — v4 breaking changes avoided"
  - "TanStack Query v5 object-form API throughout — no legacy positional args"
  - "stub pages + Layout created to prevent TS2307 compile errors in App.tsx"
metrics:
  duration: "~45 minutes"
  completed: "2026-05-18"
  tasks_completed: 3
  tasks_total: 3
  files_created: 27
  files_modified: 7
---

# Phase 4 Plan 01: API Fixes + React Scaffold Summary

**One-liner:** Fixed frames auth (removed token gate), added browser-resolvable public MinIO client, scaffolded complete React SPA with TanStack Query v5 hooks, Tailwind v3, and TypeScript type layer.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix API — remove frames auth, add public MinIO client, add missing endpoints | c275c1b | main.py, config.py, storage.py, videos.py, docker-compose.yml, .env.example |
| 2 | Scaffold React project — configs, entry points, types, settings context | 19721aa | 20 files created in services/web/ |
| 3 | API hook layer + Dockerfile upgrade | 31dbda0 | 6 api/*.ts files + Dockerfile + package-lock.json |

## What Was Built

### API Fixes (Task 1)

**frames_router auth removed:** `app.include_router(frames_router)` — no longer requires `Authorization` header. The 302 redirect resolves to a MinIO presigned URL which is self-secured via HMAC signature and 1-hour TTL. All other routers retain `Depends(require_token)`.

**Public MinIO client:** Added `MINIO_PUBLIC_ENDPOINT` and `MINIO_PUBLIC_USE_SSL` config vars. `get_public_minio_client()` creates a separate singleton using the public endpoint. `generate_presigned_url()` now calls `get_public_minio_client()` so presigned URLs contain `localhost:9000` (browser-resolvable) instead of `minio:9000` (Docker-internal only).

**New endpoints in videos.py:**
- `GET /videos` — paginated list with frame_count, detection_count, face_count (LEFT JOINs)
- `GET /videos/{id}/stream-url` — returns `{"url": "..."}` JSON for JS timestamp-seek

### React Scaffold (Task 2)

Complete Vite + React 18 + TypeScript project:
- **tsconfig.app.json:** `allowImportingTsExtensions: true`, `noEmit: true` (Vite handles emit)
- **tailwind.config.js:** v3 CommonJS syntax (`module.exports`), content glob for `src/**/*.{ts,tsx}`
- **src/types/api.ts:** 8 interfaces matching API Pydantic models exactly
- **SettingsContext:** localStorage-backed (`hvs:api_token`, `hvs:api_base_url`), survives page reload
- **Stub pages:** SearchPage, VideosPage, PeoplePage, ClustersPage, SettingsPage, Layout — prevent TS2307

### API Hook Layer (Task 3)

- **client.ts:** `authFetch` reads token from localStorage (works outside React tree in `queryFn`); skips `Content-Type` for FormData
- **persons.ts:** 5 hooks — usePersons, useCreatePerson, useEnrollPerson, useDeletePerson, useRematchPerson
- **search.ts:** `useSearch` — POST /search as useQuery; empty filter arrays → `undefined` (API semantics)
- **videos.ts:** `useVideos`, `useReIngestVideo` (calls `/ingest-api/ingest` nginx proxy path)
- **clusters.ts:** `useClusters` — gracefully returns `[]` on 404/422 (Phase 3 endpoint not yet built)
- **frames.ts:** `getFrameImageUrl(frameId)` URL builder — no fetch, used as `<img src>`
- **Dockerfile:** Multi-stage — `node:22-alpine AS build` → `npm ci` → `npm run build` → `nginx:1.27-alpine` serves `/dist`

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

| File | Reason |
|------|--------|
| src/pages/SearchPage.tsx | Replaced in Plan 02 with full search UI |
| src/pages/VideosPage.tsx | Replaced in Plan 03 with videos list UI |
| src/pages/PeoplePage.tsx | Replaced in Plan 03 with persons management UI |
| src/pages/ClustersPage.tsx | Replaced in Plan 04 with clusters UI |
| src/pages/SettingsPage.tsx | Replaced in Plan 04 with settings form |
| src/components/Layout.tsx | Replaced in Plan 02 with nav + sidebar |
| src/api/clusters.ts | Returns `[]` until Phase 3 builds GET /clusters endpoint |

These stubs are intentional scaffolding — they allow App.tsx to compile now. Plans 02–04 replace each.

## Threat Flags

None — all threat model items from the plan's `<threat_model>` were implemented:
- T-04-01: frames_router public access documented in main.py comment
- T-04-04: GET /videos uses asyncpg `$1, $2` parameterized queries (no string interpolation)
- T-04-05: GET /videos protected via videos_router `Depends(require_token)` — only frames_router is public

## Self-Check: PASSED

All verified:
- c275c1b exists: `fix(04-01): remove frames auth...`
- 19721aa exists: `feat(04-01): React scaffold...`
- 31dbda0 exists: `feat(04-01): API hook layer...`
- services/api/app/main.py — frames_router without Depends(require_token) ✓
- services/api/app/config.py — MINIO_PUBLIC_ENDPOINT ✓
- services/api/app/storage.py — get_public_minio_client() ✓
- services/api/app/videos.py — GET /videos + GET /{id}/stream-url ✓
- services/web/package.json — tailwindcss@3.4.19, react@18.3.1, @tanstack/react-query@5.100.10 ✓
- services/web/src/types/api.ts — 8 interfaces ✓
- services/web/Dockerfile — multi-stage node:22-alpine + nginx:1.27-alpine ✓
- services/web/package-lock.json — generated by npm install ✓
