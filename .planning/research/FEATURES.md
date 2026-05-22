# Features Research — v2.0: Smart Labels, Person Pages & Auto-Ingest

> **NOTE:** This file supersedes the v1.0 feature research for the three NEW features only.
> The v1.0 table-stakes / differentiator / anti-feature analysis below it remains valid as
> historical reference. Scroll to the bottom for the original v1 research.

---

**Domain:** Home security video search — incremental v2.0 feature additions  
**Researched:** 2026-05  
**Confidence:** HIGH (all three features grounded in direct codebase reading)

---

## Cluster Nickname Labeling

### Dependency on Existing System

- `unknown_clusters` table already has a `label TEXT` column (present since `001_schema.sql`). **No migration needed.**
- `ClusterResponse` Pydantic model does NOT expose `label` → needs one new field.
- `GET /clusters` SQL query does NOT SELECT `label` → needs one line change.
- `ClusterCard.tsx` has no label UI whatsoever.
- `digest.py` caption is hardcoded `"Unknown person — seen {count}×, …"` — does not check `label`.
- A new `PATCH /clusters/{id}/label` endpoint (or `PUT`) is needed; no existing endpoint handles label writes.

### Table Stakes

| Behavior | Why Expected | Notes |
|----------|--------------|-------|
| Inline edit on ClusterCard | User is already on the Clusters page; navigating away to label breaks flow | Single click-to-edit pattern (text field replaces static text) |
| Label persists across page reloads and re-cluster runs | Meaningless if it resets every night | The nightly HDBSCAN run uses stable UUIDs and only upserts `appearance_count`, `first_seen`, `last_seen`, `representative_face_id` — it does NOT clear `label`. Already safe. |
| Label visible on the cluster card in the Clusters page grid | "I labeled it — why can't I see it?" | Replace the anonymous "Unknown person" placeholder with the label, visually distinct |
| Label included in Telegram digest caption | The whole point is to reduce "Unknown person × 47" noise | Replace `"Unknown person"` with label value if not NULL |
| Empty label accepted (clear/remove a label) | User made a typo or changed their mind | PATCH accepts `null` or `""` to reset label |
| Label does NOT promote cluster to known person | These are distinct actions | Label = nickname for tracking; Promote = full enrollment with embeddings |

### Differentiators

| Behavior | Value | Notes |
|----------|-------|-------|
| Label appears in video detail faces tab | When reviewing footage, "Delivery guy" is more useful than "Unknown cluster abc123" | Faces tab already shows cluster info per frame; cluster label can be fetched via join |
| Label shown as a soft badge on cluster thumbnail | Visual differentiation — labeled clusters stand out from unnamed ones | A colored tag (e.g., amber "📎 Delivery guy") signals "we know who this is roughly" |
| Label auto-suggests from existing labels | If user has typed "delivery guy" before on another cluster, suggest it | Low complexity: `datalist` HTML element fed with distinct existing labels from API |
| Labeled clusters sorted above unlabeled ones | Once labeled, they are "known unknowns" — users want to see them first | Trivial ORDER BY `label IS NULL, label` on `GET /clusters` |

### Anti-Features / Complexity Traps

| Trap | Why to Avoid | What to Do Instead |
|------|--------------|-------------------|
| **Merging clusters on label collision** | If user labels two clusters "Delivery guy", do NOT merge their embeddings — HDBSCAN already determined they are distinct clusters | Labels are purely cosmetic; clusters remain independent |
| **Making label a first-class person** | Label ≠ enrollment; do not create a `known_persons` row, do not run pgvector rematch | Keep the promote flow separate; label is just a display string |
| **Optimistic UI that races the PATCH** | If the PATCH is slow and the user saves, then immediately clicks promote, the label may not be persisted | Use `react-query` mutation; keep the promote button disabled while label PATCH is in-flight |
| **Large freeform text / markdown** | This is a short identifier, not a notes field | Max 80 chars; plain text; no markdown rendering needed |
| **Confirmation dialog for label save** | Over-engineering a text field | Press Enter / blur to save, toast confirms |

---

## Person Appearance Page

### Dependency on Existing System

- `GET /persons/{person_id}/faces` endpoint **already exists** in `persons.py` — returns paginated `face_detections` with `frame_id`, `video_id`, `ts_ms`, `match_tier`, `match_similarity`, `thumbnail_url`.
- BUT: it returns individual face detection rows, not grouped by video. A large person (Alice with 1 400 face detections across 50 videos) produces a flat list — unsuitable for "videos they appear in."
- A second endpoint `GET /persons/{person_id}/appearances` (grouped by video, with per-video thumbnail + timestamps) is needed.
- Route `/people/:id` does NOT exist in `App.tsx` (only `/people`).
- `PersonCard.tsx` exists but has no clickable link to a detail page.
- The `GET /persons` list query and `PersonResponse` model already include `name`, `created_at`, `enrollment_count` — enough data to render a page header.

### Table Stakes

| Behavior | Why Expected | Notes |
|----------|--------------|-------|
| Route `/people/:id` navigates to a person-specific page | Core navigation pattern; clicking a person card should go somewhere | New page component + route registration |
| List of videos the person appears in | Primary value: "What videos is Alice in?" | Each row: video filename, date, thumbnail of one representative face, count of appearances in that video, link to `VideoDetailPage` at the right timestamp |
| Face thumbnail per video entry | Visual confirmation; prevents blind clicks | Use the face detection with highest `det_score` from that video as the per-video thumbnail — same `FrameThumbnail` component already in use |
| Timestamp link — click → video at first appearance | Users want to jump directly to the moment | Link to `/videos/:id` and pass `?t=ts_ms` (VideoDetailPage can seek on mount) |
| Sorted chronologically (newest first) | Security context: most recent sightings are most interesting | Default sort; togglable |
| Total count and date range in page header | "Alice — 1 400 appearances, Jan 2024 → May 2026" | Aggregate from `face_detections` — already available in existing /faces endpoint total |
| Empty state for newly enrolled person | Person exists but no footage yet matched | Simple message: "No footage found — run Rematch to scan historical videos" |

### Differentiators

| Behavior | Value | Notes |
|----------|-------|-------|
| Chronological calendar / date heat-map | "When does Alice usually appear?" — useful for understanding family routines | A simple `d3`-free implementation: group by date, render a grid of 7-day weeks with color intensity. Libraries: `react-calendar-heatmap` (2 kB, no d3 dep) or pure CSS grid. |
| Per-video appearance count badge | "Alice appears in 47 frames in this video" vs "1 frame" — helps triage | Included in the grouped `appearances` query |
| Filter by date range | Narrow to "who appeared last week" | Reuse existing date picker pattern from SearchPage |
| Match tier badge per appearance | "Confident" vs "Probable" — gives user trust signal | Already in `face_detections.match_tier` |
| "Find more" button → Rematch | If person was recently enrolled, historical footage may not be matched yet | Links to existing `POST /persons/{id}/rematch` — already implemented |

### Anti-Features / Complexity Traps

| Trap | Why to Avoid | What to Do Instead |
|------|--------------|-------------------|
| **Loading all face detections in one query** | Alice with 1 400 detections: sending all to frontend is slow and pointless | Group server-side: `SELECT video_id, COUNT(*), MIN(ts_ms), MAX(ts_ms), best_frame_id FROM face_detections ... GROUP BY video_id` — returns one row per video |
| **Infinite scroll on appearances list** | For a family member with 50 videos, pagination is unnecessary complexity | Show all videos grouped; paginate only if >100 videos (edge case) |
| **Live-updating calendar** | Page is for review, not real-time | Static render on load; no polling needed |
| **Separate "timeline" and "video list" tabs** | Small feature; two tabs fragments UX | Single page: calendar heat-map at top (collapsible), video list below |
| **Re-implementing VideoDetailPage navigation** | VideoDetailPage already handles `?t` seek | Emit a link with `?t=ts_ms` query param; VideoDetailPage handles the seek |
| **Showing every individual face detection** | Not useful; overwhelming for active family members | Show per-video grouped rows only; individual detections exist in VideoDetailPage's faces tab |

---

## Watch-Folder Auto-Ingest

### Dependency on Existing System

- `POST /ingest` on the ingestion-worker already accepts `{ minio_key: string }` and runs the full pipeline (YOLO + InsightFace + pgvector). **The entire ingestion pipeline is reused.**
- `POST /ingest` already deduplicates: if `minio_key` exists with `status=done` and `force=False`, it returns `skipped`.
- MinIO client (`minio` Python SDK) is already wired in `ingestion-worker/app/storage.py`.
- The watch-folder daemon needs to: detect file → upload to MinIO → call `POST /ingest`.
- Two viable Python options: **`watchdog`** library (cross-platform inotify wrapper) vs **inotifywait** shell script. Use `watchdog` — it runs inside Docker, same environment as the worker, no shell script maintenance.
- The daemon is a **new Docker Compose service** — a lightweight Python script, NOT embedded in the ingestion worker (no shared memory for ML models; separate process keeps memory usage clear under the 8 GB constraint).

### Table Stakes

| Behavior | Why Expected | Notes |
|----------|--------------|-------|
| New file in configured folder triggers upload + ingest automatically | That is the entire feature; anything less requires manual intervention | `watchdog` `FileSystemEventHandler.on_created` or `on_moved` |
| Only video file extensions trigger pipeline | Without this, any file (`.jpg`, `.txt`, `.tmp`) fires ingestion | Whitelist: `.mp4`, `.mov`, `.avi`, `.mkv` — matches existing `_VIDEO_EXTENSIONS` in ingestion worker |
| Skip files still being written | If a 4 GB `.mp4` is still copying when the `on_created` event fires, ingestion starts on an incomplete file | Wait until file size stops changing for N seconds (stability check: poll size every 2s, wait for 2 consecutive equal readings) |
| Idempotent restart | Daemon restarts, folder already has files — do NOT re-ingest already-processed files | `POST /ingest` returns `skipped` for `status=done` videos; daemon trusts this |
| MinIO key scheme consistent with manual upload | Files ingested via watch-folder must use the same `videos/{filename}` key so search UI works identically | Use same `MINIO_BUCKET_VIDEOS` + `videos/{filename}` path pattern |
| Configurable watch path | Not everyone has footage at `/mnt/footage` | `WATCH_FOLDER` env var; mounted as Docker volume |
| Logged clearly | User needs to know "file detected, uploaded, queued" or "skipped (already done)" | Structured log lines: `DETECTED`, `UPLOADED`, `QUEUED`, `SKIPPED`, `ERROR` |

### Differentiators

| Behavior | Value | Notes |
|----------|-------|-------|
| Recursive subdirectory watching | Camera systems often create `YYYY/MM/DD/` subdirs | `watchdog` `recursive=True` on `Observer.schedule` — trivial one-line change |
| Watch-folder status in web UI (simple) | "3 files processed today via watch-folder" — closing the feedback loop | Low effort: the existing Videos page already shows all ingested videos; watch-folder files appear there automatically. No extra UI strictly needed. |
| Configurable stability wait time | Different network mounts / cameras have different write speeds | `WATCH_STABLE_SECONDS` env var (default: 5) |
| Duplicate filename handling | Same filename dropped again (e.g., camera overwrites) | Use content hash as MinIO key suffix, OR use `videos/{date}/{filename}` path, OR rely on `minio_key UNIQUE` constraint and `?force=false` idempotency |
| File move/rename detection | Some cameras write to `.tmp` then rename to `.mp4` | Handle `on_moved` event (source `.tmp`, dest `.mp4`) in addition to `on_created` |

### Anti-Features / Complexity Traps

| Trap | Why to Avoid | What to Do Instead |
|------|--------------|-------------------|
| **Embedding watcher in ingestion-worker process** | The ingestion worker holds YOLO + InsightFace in memory (up to 3–4 GB). A second ML load for the watcher is out of the question on 8 GB RAM. | Separate lightweight Docker service (Python + watchdog + minio + requests only; ~50 MB) |
| **Using MinIO bucket event notifications instead** | MinIO events fire AFTER the file is in MinIO. The watch-folder requirement is for files dropped onto a local disk folder BEFORE they're in MinIO. These are different triggers. | Filesystem watcher is the right tool here |
| **Polling instead of inotify** | Polling every N seconds wastes CPU and introduces latency. `watchdog` uses OS-level inotify on Linux — zero polling overhead. | Use `watchdog`; set `recursive=True` |
| **Re-uploading already-uploaded files** | On restart, all files in the folder are "new" to the watcher. Re-uploading 100 GB of footage is catastrophic. | On startup, do NOT scan existing files. Let the DB idempotency handle the rare restart edge case — `POST /ingest` returns `skipped`. If re-upload risk is a concern, maintain a small local `.ingested` marker file per processed file. |
| **Processing files from multiple threads simultaneously** | i5-6200, 8 GB RAM, CPU-only ML. Two parallel ingestion jobs = OOM kill. | `POST /ingest` uses FastAPI `BackgroundTasks` which already serializes jobs (single worker thread). The watcher just fires the HTTP call — the worker queues naturally. |
| **Watch-folder UI page** | For a single-user home system, a dedicated UI page for the watcher is scope creep. | The Videos page already shows status for all ingested files. Log output is sufficient for operational visibility. |
| **Removing the manual upload button** | Watch-folder is additive, not a replacement. Manual upload via web UI is still useful for one-off files from a phone or USB drive. | Keep both paths. |

---

---

# (Original v1.0 Feature Research — archived reference)



**Domain:** Self-hosted home security video search / face recognition / family archive  
**Researched:** 2025-05  
**Sources:** Frigate NVR v0.17.1 docs, Double Take README, CompreFace README, Telegram Bot API, requirements.md analysis  
**Overall confidence:** HIGH (core features verified against live docs; clustering UX patterns MEDIUM)

---

## Table Stakes

Features users expect. Missing = the tool is useless or feels broken.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Video library list with ingestion status | Users need to know what's been indexed and what's pending/failed | Low | `pending → processing → done → failed`; re-ingest button |
| Frame-accurate playback deep link | Without this, "finding" a face is pointless — you still have to scrub manually | Low | `<video currentTime = ts_ms / 1000>` via presigned MinIO URL |
| Filter by known person | Core search primitive — must work for named family members | Low | Multi-select from enrolled persons list |
| Filter by date range | Security review is always time-bounded | Low | `date_from / date_to` on `recorded_at` |
| Filter by object class (car, person, dog) | Non-face object search for general review | Low | COCO classes from YOLO |
| Face enrollment UI | No enrollment = no recognition = no value | Medium | Upload 5–10 photos per person; reject multi-face or no-face images |
| Unknown face flag | User must know when an unrecognized face was found | Low | `matched_person_id IS NULL` in DB |
| Thumbnail grid results | Frame-level results with visual confirmation before clicking through | Low | Grid of `frames/{video_id}/{ts_ms}.jpg` images |
| Ingestion status + error display | When processing fails, user needs to see why (disk full, corrupt video, etc.) | Low | `error_message` column on `videos` |
| Re-ingest / force reprocess | Videos sometimes need re-indexing (new person enrolled retroactively) | Low | `?force=true` on ingest endpoint |
| Basic auth / token protection | Security footage is private; open access is unacceptable | Low | Bearer token middleware |

**Verdict:** The requirements.md already covers all table-stakes items. No gaps identified.

---

## Differentiators

Features that make this significantly better than manually reviewing footage or using Frigate as-is.

### 1. Unknown Face Clustering (PRIMARY differentiator — v1 required)

**What it is:** Group unknown faces by identity using DBSCAN/HDBSCAN on ArcFace 512-dim embeddings. Instead of showing 847 individual "unknown" face crops, show 12 clusters ("Stranger A appeared 43 times across 6 videos", "Stranger B appeared 8 times").

**Why it's a differentiator:** Frigate v0.17.x does NOT cluster unknowns. It shows all unrecognized faces in a "Train" tab as a flat list — usable for enrolling new people but unusable for surveillance review at scale. ZoneMinder and Shinobi have no face search at all.

**UX pattern (recommended):**
```
Unknowns page:
┌──────────────────────────────────────────────────────┐
│ Unknown Faces — 14 clusters found                    │
│                                                      │
│ [Photo] Cluster A   │ [Photo] Cluster B   │ ...      │
│ 43 appearances      │ 8 appearances       │          │
│ First: 2025-01-03   │ First: 2025-03-12   │          │
│ Last: 2025-05-14    │ Last: 2025-05-10    │          │
│ [Enroll as person]  │ [Enroll as person]  │          │
│ [Mark as recurring  │ [Dismiss as noise]  │          │
│  delivery]          │                     │          │
└──────────────────────────────────────────────────────┘
```

**Implementation approach:**
- Run after ingestion pipeline completes
- Fetch all embeddings where `matched_person_id IS NULL`
- Apply DBSCAN with cosine distance metric (epsilon ~0.4, min_samples ~3)
- Store cluster assignments in a `face_clusters` table (cluster_id, representative_embedding, label, count)
- "Enroll from cluster" action: creates a `known_persons` entry and assigns all cluster members to it retroactively
- Re-cluster on a schedule (daily) or on demand after enrollment

**Schema addition needed:**
```sql
CREATE TABLE face_clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    representative_face_id BIGINT REFERENCES face_detections(id),
    label           TEXT,   -- user-assigned label (nullable = unlabeled)
    cluster_algo    TEXT DEFAULT 'dbscan',
    clustered_at    TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE face_detections ADD COLUMN cluster_id UUID REFERENCES face_clusters(id);
```

---

### 2. Daily Telegram Digest (v1 required)

See dedicated section below. Differentiator because no open-source NVR does this out of the box; Frigate's notifications are WebPush only (requires browser registration, internet connectivity to push servers).

---

### 3. Retroactive Search After Enrollment

**What it is:** When a new person is enrolled, the user can trigger a re-scan that rematches all stored embeddings against the new person's embedding — without re-extracting frames or re-running YOLO/InsightFace. Purely a pgvector query.

**Why it's a differentiator:** Frigate cannot do this — it processes live streams only. This system has all embeddings stored, so retroactive matching is a ~1-second SQL query:

```sql
UPDATE face_detections
SET matched_person_id = $person_id, match_similarity = 1 - (embedding <=> $new_embedding::vector)
WHERE 1 - (embedding <=> $new_embedding::vector) >= $threshold
  AND matched_person_id IS NULL;
```

**UX:** "Scan historical footage for [Name]" button on the People page. Shows progress, then surfaces results.

---

### 4. Batch Import from MinIO Prefix

**What it is:** Trigger re-ingestion of an entire folder (e.g., `videos/2024/`) via a single API call rather than one-by-one.

**Why it's a differentiator:** Existing tools assume you're adding cameras, not importing an existing archive. The `POST /ingest/batch` endpoint scanning a MinIO prefix is essential for the initial archive import scenario.

---

### 5. Video-Level Summary on Ingestion Completion

**What it is:** After processing, the video record shows: total detections, persons recognized (names + counts), unknown face count, object class breakdown.

```json
{
  "video_id": "...",
  "persons_found": ["Alice (12 frames)", "Bob (3 frames)"],
  "unknown_faces": 5,
  "objects": {"car": 8, "dog": 1}
}
```

**Why it's a differentiator:** Lets the user triage without opening every video. "Mostly family" vs "unfamiliar faces" visible at a glance in the Videos list.

---

### 6. "Find Similar" from Any Face Crop

**What it is:** Click on any detected face thumbnail → "Find similar faces" → pgvector ANN search returns the nearest N faces across all footage. Useful for confirming cluster assignments or tracking a specific unknown across cameras/days.

**Why it's a differentiator:** Frigate added this (semantic "Find Similar") but it's image-level, not face-embedding-level. Using ArcFace embeddings means the similarity is identity-aware, not just visual appearance.

---

## Anti-Features (v1)

Features to deliberately NOT build. Building these wastes time and adds complexity that degrades the core value.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Live stream / RTSP camera support** | Requires continuous processing pipeline, FFmpeg RTSP reader, buffer management — completely different architecture from batch. The existing use case is archive review, not real-time. | Process saved video files only; Frigate already handles live cameras. |
| **Real-time alerts on detection** | Requires event streaming (WebSocket or SSE), low-latency pipeline. Out of scope for batch indexing system; adds operational complexity. | Daily digest covers the security use case adequately for v1. |
| **Mobile app** | Web UI with responsive Tailwind CSS is sufficient for family single-user. Native app is 3× the development effort. | Responsive web UI; Telegram digest is the mobile touchpoint. |
| **Audio analysis / speech recognition** | No use case defined. Adds Whisper/VAD pipeline, significantly increases processing time, inflates storage. | Stick to visual analysis only. |
| **Multi-user auth / roles** | Single family, single shared login. Role management = YAGNI. | Single `API_TOKEN` env var. |
| **Person re-ID without face** (body/gait) | Extremely complex, low accuracy on consumer cameras, high false positive rate. InsightFace only when face is visible. | YOLO `person` class covers "was a person here?" without identity. |
| **Automatic clip generation / highlights reel** | Nice idea but scope creep. Requires defining "interesting" heuristics. | Users jump to specific frames via deep link. |
| **Cloud sync / backup** | Self-hosted, data stays local. Cloud adds privacy concerns + cost. | MinIO is the local durable store. |
| **"Smart" zones / masks per camera** | Only relevant for live-stream NVRs. This system processes whole frames from saved files. | YOLO bbox data captures position; no masking needed for batch review. |
| **On-device training / fine-tuning** | ArcFace models are pre-trained; fine-tuning requires GPU and careful data management. InsightFace's enrollment-via-embedding approach is correct for this scale. | Enroll 5–20 reference images per person; no fine-tuning. |
| **Face age/gender/emotion attributes** | Adds latency (extra InsightFace models), raises privacy concerns, no defined use case. | Store only bbox + embedding + match result. |

---

## Telegram Digest: Recommended Content

**Purpose:** Morning summary (08:00) of what happened in the last 24 hours. Replaces the need to log into the web UI daily. Acts as a "nothing unusual" signal when it's quiet.

**Delivery mechanism:** n8n cron workflow → query FastAPI `/search` endpoint → format → `sendMessage` (+ `sendPhoto` per cluster) via Telegram Bot API.

**Telegram capabilities relevant here:**
- `sendMessage` with `parse_mode=HTML` or `MarkdownV2` — inline links, bold, code spans
- `sendPhoto` with `caption` — photo + text in one message (caption ≤ 1024 chars)
- `sendMediaGroup` — up to 10 photos in one grouped message (useful for face cluster thumbnails)
- Inline buttons (`reply_markup`) — "View in app" button with deep link to the web UI

---

### Digest Message Structure

**Message 1: Header summary**
```
📹 Daily Security Digest — Wednesday 14 May 2025

📊 Activity Summary
  Videos processed today: 3
  Total footage reviewed: 4h 12m
  Frames analyzed: 15,082

👨‍👩‍👧 Family Activity
  • Alice — 47 appearances across 3 videos
    First seen: 08:12 in backyard_cam_2025-05-14.mp4
    Last seen: 21:43 in frontdoor_cam_2025-05-14.mp4
  • Bob — 12 appearances in 1 video (garage_cam_2025-05-14.mp4)
  • No appearances: Carol (expected away)

⚠️ Unknown Faces — ACTION NEEDED
  • Cluster A: 15 appearances (3 videos) — [View →]
  • Cluster B: 4 appearances (1 video, 14:20–14:35) — [View →]
  • 3 isolated unknowns (single appearance, likely noise)

🚗 Object Detections
  • 8 vehicles (6 known time windows, 2 outside routine hours ⚠️)
  • 1 dog

[🔍 Open Search UI]  [📚 Review Unknowns]
```

**Message 2 (if unknowns exist): Photo group of cluster representatives**
```
sendMediaGroup([
  { photo: cluster_A_representative_thumbnail, caption: "Cluster A: 15 appearances" },
  { photo: cluster_B_representative_thumbnail, caption: "Cluster B: 4 appearances" }
])
```

---

### Specific Fields Required in Digest

| Field | Source | Fallback if empty |
|-------|--------|------------------|
| Date of digest | n8n trigger timestamp | — |
| Videos processed in last 24h | `SELECT COUNT(*) FROM videos WHERE ingested_at > now() - interval '24h'` | "No new videos indexed" |
| Total footage duration | `SUM(duration_sec)` | — |
| Per-person appearance counts | `COUNT(DISTINCT frame_id)` per `matched_person_id` | "Not seen today" |
| Per-person first/last appearance timestamp | `MIN/MAX(recorded_at + interval ts_ms)` | — |
| Per-person source video filename | Join to `videos.filename` | — |
| Unknown cluster count | Count of cluster_ids not labeled as known person | Omit section |
| Per-cluster appearance count | Count of `face_detections` per `cluster_id` | — |
| Per-cluster representative thumbnail URL | MinIO presigned URL for `representative_face_id` frame crop | — |
| Out-of-hours vehicle count | Detections outside configurable window (e.g., 22:00–06:00) | — |
| Deep link to web UI | `https://search.shumov.eu/unknowns?cluster=A` | — |

---

### Digest Design Principles

1. **Silence is signal.** If nothing unusual happened, the message should be short: "✅ All quiet — Alice (23 appearances), Bob (5). No unknowns." Don't pad with stats.
2. **Photos for unknowns, text for known family.** Family members don't need thumbnail proof. Unknowns do.
3. **Actionable deep links.** Every "Cluster A — 15 appearances" should link directly to the filtered unknown clusters view in the web UI.
4. **Threshold noise suppression.** Single-frame unknowns (1–2 appearances) should be grouped as "isolated detections" or suppressed entirely to avoid alert fatigue.
5. **Time-zone aware.** The digest must use the local timezone (`Europe/Moscow` or configurable env var), not UTC.

---

## Comparison: How This Differs from Existing Tools

### Frigate NVR (v0.17.1)

| Feature | Frigate | HomeVideoSearcher |
|---------|---------|-------------------|
| Primary use case | Live camera monitoring | **Archive search / batch indexing** |
| Face recognition | ✅ ArcFace (GPU), FaceNet (CPU) | ✅ ArcFace via InsightFace (CPU) |
| Unknown face handling | Flat list in "Train" tab, manual labeling | **DBSCAN clustering → labeled groups → enroll from cluster** |
| Semantic search | ✅ CLIP-based (text → video, image → image) | ✅ Embedding-based face search; object class search |
| Telegram notifications | ❌ WebPush only (Google FCM dependency, browser required) | ✅ Native Telegram digest via n8n |
| Retroactive re-scan after enrollment | ❌ Cannot re-process historical footage | ✅ pgvector re-match against stored embeddings |
| Archive import (batch files) | ❌ Requires RTSP camera config | ✅ MinIO batch prefix scan |
| Hardware requirement | GPU strongly recommended for accurate face recog | CPU-only (i5-6200) by design |
| Self-hosted complexity | High (Frigate + MQTT + HA for notifications) | Low (Docker Compose, 4 services) |

**Key gap Frigate has:** Unknown clustering. Frigate v0.17 shows all unknowns as a flat feed. If a delivery person visits 40 times in 6 months, Frigate shows 40 separate anonymous entries. HomeVideoSearcher clusters them as "Cluster A: 40 appearances" recognizable as one recurring person.

---

### Shinobi NVR

| Feature | Shinobi | HomeVideoSearcher |
|---------|---------|-------------------|
| AI face recognition | ❌ (plugin-based, limited) | ✅ InsightFace ArcFace |
| Video search by person | ❌ | ✅ |
| Unknown clustering | ❌ | ✅ |
| Telegram | ✅ (motion alert, no digest) | ✅ (structured daily digest) |
| Batch archive processing | ⚠️ Manual | ✅ n8n + MinIO events |

---

### ZoneMinder

| Feature | ZoneMinder | HomeVideoSearcher |
|---------|-----------|-------------------|
| AI face recognition | ❌ (requires external plugin) | ✅ Built in |
| Video search by face | ❌ | ✅ |
| Self-hosting complexity | High (C++, MySQL, Perl deps) | Low (Python + Docker) |
| Modern web UI | ❌ (dated PHP UI) | ✅ React + Vite |

---

### Double Take (face recognition middleware)

| Feature | Double Take | HomeVideoSearcher |
|---------|------------|-------------------|
| Face recognition approach | Routes to external services (CompreFace, DeepStack) | ✅ All-in-one (InsightFace embedded) |
| Archive search | ❌ (event-driven, real-time only) | ✅ |
| Unknown clustering | ❌ | ✅ |
| Telegram digest | ❌ | ✅ |

---

## Feature Dependency Map

```
Frame extraction (FFmpeg)
  └→ Object detection (YOLO)
       └→ Person class detected
            └→ Face detection + embedding (InsightFace)
                 ├→ Known face match (pgvector cosine)
                 │    └→ Search UI: filter by person
                 │    └→ Telegram digest: family appearances
                 └→ Unknown face (no match above threshold)
                      └→ DBSCAN clustering (offline job)
                           └→ Unknown clusters UI
                           └→ Telegram digest: cluster alerts
                           └→ Enroll from cluster → retroactive re-match

Ingestion trigger (n8n MinIO event)
  └→ Batch import (MinIO prefix scan)
  └→ Daily digest cron (n8n 08:00)
```

---

## MVP Prioritization

**Must have for v1 (this project):**
1. Full ingestion pipeline (FFmpeg → YOLO → InsightFace → pgvector)
2. Face enrollment UI (5–10 images, rejection of multi-face images)
3. Search UI: filter by person + object class + date range
4. Frame-accurate video playback deep link
5. Unknown face clustering (DBSCAN on stored embeddings)
6. Unknown clusters review page
7. Daily Telegram digest via n8n

**Defer to v2:**
- "Find similar" face search from UI (pgvector ANN is trivial, but UI clickthrough needs design)
- Out-of-hours vehicle alert in digest (requires configurable schedule window)
- Retroactive scan button in UI (backend is trivial; UX for progress display is work)
- Cluster auto-labeling suggestions (match cluster centroid against known persons with lower threshold)

## Sources

- Frigate NVR v0.17.1 face recognition docs: `https://raw.githubusercontent.com/blakeblackshear/frigate/dev/docs/docs/configuration/face_recognition.md` (HIGH confidence)
- Frigate NVR notifications docs: `https://raw.githubusercontent.com/blakeblackshear/frigate/dev/docs/docs/configuration/notifications.md` (HIGH confidence)
- Frigate semantic search docs: `https://raw.githubusercontent.com/blakeblackshear/frigate/dev/docs/docs/configuration/semantic_search.md` (HIGH confidence)
- Double Take README: `https://github.com/skrashevich/double-take` (HIGH confidence)
- CompreFace README: `https://github.com/exadel-inc/CompreFace` (HIGH confidence)
- Telegram Bot API: `https://core.telegram.org/bots/api` (HIGH confidence)
- Project requirements.md: direct analysis (HIGH confidence)
- DBSCAN for face clustering: standard ML approach, multiple published implementations (MEDIUM confidence — specific epsilon values need empirical tuning per ArcFace embedding space)
