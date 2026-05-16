# Features Research: HomeVideoSearcher

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
