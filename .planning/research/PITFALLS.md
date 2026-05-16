# Pitfalls: HomeVideoSearcher

**Domain:** Self-hosted video analytics with face recognition  
**Hardware:** i5-6200, 8 GB RAM, CPU-only  
**Stack:** InsightFace buffalo_l · YOLOv8n · PostgreSQL 16 + pgvector HNSW · MinIO · Docker Compose  
**Researched:** 2025-05-16  
**Confidence:** HIGH (pitfalls drawn from known failure modes of each named library/component)

---

## Face Recognition Pitfalls

### Pitfall FR-1: Threshold 0.5 Is Too Permissive for High-Precision Family Use

**What goes wrong:** The requirements specify a default `FACE_MATCH_THRESHOLD = 0.5` cosine similarity. For buffalo_l / ArcFace on a clean, controlled enrollment set this is on the low end — in practice, distant relatives, people wearing hats, or low-resolution frames routinely produce similarities in the 0.45–0.55 range. At 0.5 you will get false positives: the system labels an unknown visitor as "Dad."

**Why it happens:** ArcFace was trained to produce **large inter-class margins on high-quality frontal images**. When inference images are low-res security camera frames (motion blur, night-mode grain, wide angle), the embedding drifts toward the mean and cosine similarity for correct matches can drop to 0.55–0.65 while wrong matches can climb to 0.48–0.52.

**Consequences:** False positive identifications appear in the "Dad appeared" Telegram digest. Once the user stops trusting the system it is effectively dead.

**Prevention:**
- Start threshold at **0.60–0.65**, not 0.5. Validate against your actual camera footage before going to production.
- Implement a **two-tier threshold**: ≥ 0.65 → confident match (labeled + notified); 0.50–0.65 → "possible match" (stored but flagged for manual review, not sent in digest).
- Add a metric: log the histogram of `match_similarity` values for known persons to `logs/` over the first week. Let the distribution tell you where to put the threshold.
- Never report a person as "appeared" in a Telegram message unless the similarity is above the high-confidence tier.

**Detection (warning signs):**
- Same frame shows the same person labeled with two different names across re-runs.
- A person's appearance count grows 3–5× faster than expected for their screen time.

**Phase/component:** Face pipeline (`faces.py`), ingestion-worker — address at Phase 1 before any notifications are wired up.

---

### Pitfall FR-2: Single Enrollment Image Per Person

**What goes wrong:** The requirements say "upload 1–N images" but users almost always upload just 1 ("here's a photo from last Christmas"). With a single embedding, there is zero coverage of lighting variation, angle, aging, glasses, hats, or hair changes. Recognition accuracy for that person collapses in varied footage.

**Why it happens:** Convenience. The UI makes 1 image easy and doesn't enforce more.

**Consequences:** The known person is missed in 40–60% of frames where they actually appear. The user concludes the system "doesn't work" for that person.

**Prevention:**
- **Enforce a minimum of 3 enrollment images** in the API (`POST /persons/{id}/enroll`). Reject with `422` if fewer are provided on the first enrollment.
- Show a warning in the UI if fewer than 5 images are enrolled ("Face recognition accuracy is reduced with fewer than 5 images").
- When enrolling, run a diversity check: if all embeddings are within cosine distance 0.05 of each other, warn "These images look too similar — add images with different lighting or angles."
- Store multiple embeddings per person (already in the schema as `person_embeddings` — good). During matching, compare against **all** embeddings and take the **max** similarity.

**Detection (warning signs):** A person has exactly 1 embedding in `person_embeddings` but many `NULL` matches in `face_detections` for frames where they visually appear.

**Phase/component:** Enrollment API (`persons.py`), People page (web UI) — address at Phase 1.

---

### Pitfall FR-3: Running InsightFace on Full Frame Always (Slow on 8 GB CPU)

**What goes wrong:** The requirements correctly note to run InsightFace on the full frame, not YOLO crops. However, at `det_size=(640, 640)` on a 1920×1080 frame, SCRFD's pyramid runs on the full image. If there are 0 faces in the frame (a car-only clip), you've paid the full ~0.8s inference cost for nothing.

**Why it happens:** The simple path is `app.get(frame_bgr)` on every frame unconditionally.

**Consequences:** Processing time doubles for footage that is not person-heavy (parking lot, street views). On the i5-6200 this can mean a 2-hour video that should take 3 hours takes 6 hours.

**Prevention:**
- **Gate InsightFace on YOLO person detections**: only call `app.get()` on frames where YOLO detected at least one `person` class object with confidence ≥ 0.35.
- This is already implied by the architecture — enforce it in `pipeline.py` with an explicit `if not has_person_detection(frame): continue` before the face pipeline.
- For the security use-case (unknown visitors) this is correct: if no person is detected, there's no face to find.

**Detection (warning signs):** `time_face_pipeline / time_total` is > 80% even for videos that are mostly vehicles.

**Phase/component:** `pipeline.py` — critical path decision, address at Phase 1.

---

### Pitfall FR-4: Not Normalizing Embeddings Before Storage

**What goes wrong:** The requirements correctly call out using `face.normed_embedding`. But if a developer accesses `face.embedding` instead of `face.normed_embedding` anywhere in the codebase (easy to do — they're both available), or if enrollment images go through a different code path, raw embeddings are stored alongside normalized ones. pgvector's cosine distance (`<=>`) assumes normalized vectors — mixing normalized and un-normalized embeddings silently produces meaningless similarity scores.

**Why it happens:** InsightFace exposes both `face.embedding` (raw) and `face.normed_embedding` (L2-normalized). The distinction is not obvious from IDE autocomplete.

**Consequences:** A person's enrollment embeddings compare incorrectly against detection embeddings. False negatives dominate — the person is never matched.

**Prevention:**
- Create a single utility function `normalize_embedding(v: np.ndarray) -> np.ndarray` that always L2-normalizes, and call it on **every** embedding before storage — even `normed_embedding`, as a defensive measure.
- Add a database-level CHECK or trigger that asserts `|embedding| ≈ 1.0` (within 1e-4). Alternatively, add a startup self-test that enrolls a synthetic embedding and checks that similarity with itself is ≥ 0.9999.
- Unit test: verify `np.dot(emb, emb) ≈ 1.0` after normalization.

**Detection (warning signs):** Cosine similarities for the same person across frames cluster near 0 instead of near 1.

**Phase/component:** `faces.py`, `db.py` — must be correct before any data is written; Phase 1.

---

### Pitfall FR-5: Enrollment Image Quality Not Validated

**What goes wrong:** A user uploads a group photo (multiple faces), a blurry thumbnail, or an image where the face is less than 50px wide. InsightFace may detect a face and compute an embedding, but the embedding will be low-quality, hurting recognition for all future frames.

**Why it happens:** The API just runs `app.get(image)` and takes the first face it finds.

**Consequences:** One bad enrollment image degrades the entire person's recognition. No obvious error is raised.

**Prevention:**
- Reject enrollment if `det_score < 0.7` (low detector confidence = blurry or angled face).
- Reject if face bounding box is smaller than 80×80 pixels.
- Reject if multiple faces are detected (the API spec already says to do this — enforce strictly).
- Log which enrollment images were accepted/rejected with reasons.

**Detection (warning signs):** Recognition accuracy for a person was fine, then drops after adding a new photo.

**Phase/component:** `POST /persons/{id}/enroll` in `persons.py` — Phase 1.

---

## Memory / Hardware Pitfalls

### Pitfall MEM-1: Loading Both Models Simultaneously in the Same Process

**What goes wrong:** If `pipeline.py` loads YOLO and InsightFace at startup in the same process, combined RSS is approximately 0.5 GB (YOLO) + 1.5 GB (InsightFace) + Python overhead = ~2.5 GB. Under frame processing, ONNX runtime allocates working memory: YOLO adds ~200 MB, InsightFace adds ~400 MB. Add PostgreSQL (~1 GB), OS + buffers (~1.5 GB), and you're at 5.5–6 GB. This leaves <2 GB headroom — any upstream MinIO frame buffering or a large video frame allocation will OOM.

**Why it happens:** The simple approach is to load everything at startup in one process. ONNX Runtime does not release intermediate tensors aggressively on CPU.

**Consequences:** The ingestion worker is OOM-killed mid-batch, the video is left in `processing` state permanently (zombie jobs), and the OS swap thrashes, making the i5-6200 effectively unusable during batch runs.

**Prevention:**
- Load models **once** at worker startup (correct) but process frames **sequentially**: YOLO first, save detections, then InsightFace. Never overlap their inference calls.
- Set `OMP_NUM_THREADS=4` (already in requirements) to prevent ONNX from spawning excess threads that each allocate their own working memory.
- Set `ONNX_DISABLE_GPU=1` explicitly (not needed for CPU, but prevents accidental CUDA provider init that can bloat memory).
- Keep frame buffer size small: stream frames from FFmpeg one at a time instead of extracting all frames to disk before processing. Alternatively, extract to `/tmp` with a cap and process + delete in a sliding window.
- Deploy a 4 GB swap file on the Ubuntu host as a safety net (mentioned in requirements — make this a Day 0 ops task).
- Set Docker memory limit to 5 GB for ingestion-worker (already in requirements.md — good). Add `memswap_limit: 7g` to allow swap without OOM-kill.

**Detection (warning signs):** `docker stats` shows ingestion-worker memory approaching 4.5 GB. `dmesg | grep -i oom` on host.

**Phase/component:** `pipeline.py`, `docker-compose.yml` — Phase 1, verified before batch processing of any real library.

---

### Pitfall MEM-2: FFmpeg Extracting All Frames Before Processing Begins

**What goes wrong:** The naive implementation calls FFmpeg to extract all frames from a 1-hour video (3,600 JPEG files at ~200 KB each = 720 MB on disk), then starts the ML pipeline. On an 8 GB system with `/tmp` on the root filesystem, this can fill the disk or exhaust `/tmp` tmpfs.

**Why it happens:** It's simpler to write one FFmpeg call that dumps all frames, then iterate.

**Consequences:** Disk exhaustion or tmpfs exhaustion causes the FFmpeg process to error, or silently truncates the frame dump. The video is partially indexed without an error in the DB.

**Prevention:**
- Use FFmpeg's **pipe mode**: stream frames via `stdout` and process each one in memory, or extract to `/tmp/work/{video_id}/` (Docker volume) with a **frame-sliding window**: extract 60 frames, process them, delete them, extract next 60.
- Cap `/tmp/work` Docker volume size, or use a bind-mount with `df` monitoring.
- Alternative: use `ffmpeg -ss {time} -i input.mp4 -vframes 1 frame.jpg` in a loop — slower but zero disk accumulation.

**Detection (warning signs):** `df -h /tmp` spikes during ingestion. Long pause before any DB writes.

**Phase/component:** `frames.py` — Phase 1.

---

### Pitfall MEM-3: pgvector HNSW Index Build OOM During Bulk Insert

**What goes wrong:** When ingesting a large initial library (say, 50,000 face embeddings), pgvector rebuilds the HNSW index incrementally. The index build holds the entire graph in shared memory. With default PostgreSQL settings (`shared_buffers=128MB`), the build will be slow. If someone increases `shared_buffers` aggressively, index build can OOM the machine.

**Why it happens:** HNSW index maintenance overhead is `O(M × ef_construction × d)` per insertion, where d=512. For bulk inserts, this accumulates.

**Consequences:** PostgreSQL crashes mid-insert, leaving the index in an inconsistent state. The `face_detections` table is partially indexed.

**Prevention:**
- For the initial bulk import, **drop the HNSW index, bulk-insert all embeddings, then recreate the index**. This is dramatically faster and uses a controlled memory budget.
- Use `SET maintenance_work_mem = '512MB'` only during the index build session, not globally.
- In steady-state (single video per night), incremental HNSW updates are fine and won't OOM.
- PostgreSQL config for this hardware: `shared_buffers=256MB`, `work_mem=32MB`, `maintenance_work_mem=256MB` — conservative values that leave room for the ML worker.

**Detection (warning signs):** PostgreSQL log shows `out of memory` or `could not resize shared memory segment`. Slow index builds (>5 min for < 10k rows).

**Phase/component:** `db/init/001_schema.sql`, `docker-compose.yml` postgres config — Phase 1.

---

### Pitfall MEM-4: ONNX Runtime Thread Contention With PostgreSQL

**What goes wrong:** On the i5-6200 (2 cores / 4 threads), setting `OMP_NUM_THREADS=4` means the ML worker can saturate all CPU threads. When PostgreSQL simultaneously tries to execute a vector similarity query, it starves. Database latency spikes, asyncpg connections time out, and the ingestion worker fails with connection errors.

**Why it happens:** Both ONNX Runtime and PostgreSQL use multi-threaded execution and compete for the same 4 logical CPUs.

**Consequences:** Random ingestion failures with `asyncpg.exceptions.QueryCanceledError` or connection timeouts, appearing to be database bugs.

**Prevention:**
- Set `OMP_NUM_THREADS=2` or `OMP_NUM_THREADS=3` instead of 4, leaving one thread for PostgreSQL I/O.
- Process pipeline steps sequentially and do DB writes **after** all ML inference for a frame is complete — don't interleave inference and DB queries.
- Use `INTRA_OP_NUM_THREADS=2, INTER_OP_NUM_THREADS=2` in ONNX Runtime session options for fine-grained control instead of `OMP_NUM_THREADS` alone.

**Detection (warning signs):** `top` shows `ort` threads and `postgres` processes both fighting for 100% CPU. DB latency > 500ms for simple queries during ingestion.

**Phase/component:** `config.py`, `faces.py`, `detect.py` — Phase 1.

---

## Clustering Pitfalls

### Pitfall CL-1: Running DBSCAN Over All Unknown Face Embeddings at Once

**What goes wrong:** DBSCAN with sklearn's default implementation is `O(n²)` in memory for the distance matrix (or `O(n × k)` with ball tree, which still requires all embeddings in RAM). At 10,000 unknown face embeddings of 512 float32 values each, the raw embeddings alone are 20 MB — manageable. But the pairwise cosine distance matrix is 10,000 × 10,000 × 4 bytes = 400 MB, which is fine... until it's 50,000 embeddings: 10 GB. On 8 GB RAM, this OOMs immediately.

**Why it happens:** The default `sklearn.cluster.DBSCAN` with `metric='cosine'` computes the full pairwise distance matrix unless `algorithm='ball_tree'` or `'kd_tree'` is specified. Even with `algorithm='ball_tree'`, cosine distance is not natively supported (only Euclidean and Minkowski). The common workaround (normalize + Euclidean) works but is easy to get wrong.

**Consequences:** Clustering job OOMs and crashes the ingestion worker. All unknown faces remain ungrouped.

**Prevention:**
- **Use HDBSCAN** (via `hdbscan` Python package) instead of DBSCAN. HDBSCAN with `metric='cosine'` uses a ball tree internally and does not materialize the full distance matrix. It also handles varying density better (surveillance footage has dense clusters around frequent visitors and sparse clusters for rare ones).
- Alternatively, use **pgvector itself for clustering**: pull unknown embeddings from the DB in batches, and use a greedy nearest-neighbor approach against pgvector's HNSW index (already built for `face_detections`). Each new unknown face queries its nearest neighbor — if distance < ε, add to that cluster; otherwise create a new cluster. This is an incremental online algorithm that never OOMs.
- Set a hard limit: cluster only embeddings from the last 30 days to cap n.
- For v1, the pgvector-based greedy approach is the right choice: it reuses existing infrastructure, has no additional dependencies, and scales incrementally.

**Detection (warning signs):** Clustering job never completes. `docker stats` shows ingestion-worker RAM hitting ceiling during the cluster step.

**Phase/component:** Clustering service / cron job — Phase 2. Design this from scratch with the pgvector incremental approach, not a DBSCAN afterthought.

---

### Pitfall CL-2: DBSCAN / HDBSCAN Epsilon Tuning — Getting a Single Giant Cluster

**What goes wrong:** With face embeddings from security camera footage, cosine distances between different people can be surprisingly small (0.2–0.4) when lighting conditions are similar (e.g., all nighttime infrared shots produce similar-looking embeddings). Setting epsilon too high (e.g., ε = 0.6) causes everyone to be clustered into one giant "unknown person" cluster.

**Why it happens:** Epsilon is usually set based on indoor/studio face datasets. Security camera footage has much lower embedding variance per person, meaning inter-person distances are compressed.

**Consequences:** The daily Telegram digest reports "1 unknown cluster with 847 faces" — useless for identifying specific visitors.

**Prevention:**
- The right epsilon for buffalo_l / ArcFace on security footage is **ε = 0.35–0.45** (cosine distance), not the 0.5–0.6 sometimes cited for studio photos. Start at 0.35.
- Run the clustering algorithm on a **validation set** before trusting it: manually label 50–100 unknown face crops from your actual cameras and tune ε until the clustering matches your manual labels.
- Surface cluster quality metrics in the admin UI: number of clusters, mean cluster size, number of singletons. If #clusters = 1 or #singletons > 80%, the threshold is wrong.
- Store ε as a configurable env var (`CLUSTER_EPSILON=0.40`), not hardcoded.

**Detection (warning signs):** All unknown faces land in 1–3 clusters. Singletons make up < 5% of embeddings.

**Phase/component:** Clustering service — Phase 2.

---

### Pitfall CL-3: Cluster Identity Drift Over Time (No Stable Cluster IDs)

**What goes wrong:** On the first clustering run, "Stranger A" gets cluster ID `uuid-abc`. On the next nightly run, embeddings are re-clustered from scratch. Due to new data points changing cluster shapes, "Stranger A" may now be cluster `uuid-def`. Any UI labels the user applied ("this is the delivery driver") are now orphaned.

**Why it happens:** Batch re-clustering assigns new IDs every run if the algorithm doesn't have a concept of cluster identity persistence.

**Consequences:** The user labels a recurring unknown visitor, then the next day that label is gone. The Telegram digest shows "new unknown cluster" for someone the user already knows is the delivery driver.

**Prevention:**
- **Never re-cluster from scratch after v1 launch.** Use an **incremental clustering strategy**: assign new (unassigned) unknown face embeddings to existing clusters if their nearest cluster centroid is within ε; otherwise create a new cluster. This preserves cluster IDs.
- Store a `cluster_centroid` vector per cluster (updated as a running mean as new faces are added). When a new face arrives, query pgvector for the nearest cluster centroid; if distance < ε, assign to that cluster.
- Add a `unknown_clusters` table with stable UUID, centroid vector, and `user_label` (nullable). User labels survive re-clustering because they're attached to the UUID, not re-derived from the algorithm.
- Reserve full re-clustering as an explicit admin action ("Rebuild all clusters") that warns the user labels will be reset.

**Detection (warning signs):** `unknown_clusters` count resets or changes dramatically between nightly runs. User-applied labels disappear.

**Phase/component:** `unknown_clusters` table + clustering cron — Phase 2. Design the schema for incremental clustering before implementing.

---

### Pitfall CL-4: Clustering Known-Person Faces as Unknown

**What goes wrong:** A known person (enrolled) appears in a video, but the frame is low-quality enough that `match_similarity < FACE_MATCH_THRESHOLD`. The face is stored with `matched_person_id = NULL` and gets ingested into the unknown clustering pool. That person's face now pollutes the unknown clusters and may form their own cluster, leading to Telegram notifications about "unknown person" who is actually Mom.

**Why it happens:** The binary threshold (match vs. no-match) doesn't have a concept of "probable match, below threshold."

**Consequences:** Notification fatigue and false security alerts about enrolled family members.

**Prevention:**
- Use the **two-tier threshold** from FR-1: 0.65+ = confirmed match, 0.50–0.65 = probable match.
- Faces with `match_similarity` in the probable range (0.50–0.65) should be stored with `matched_person_id = <person>` but flagged as `low_confidence = TRUE` — they must NOT enter the unknown clustering pool.
- Faces with `match_similarity < 0.50` are genuine unknowns → clustering pool.
- Add a `probable_person_id` column to `face_detections` for the middle tier.

**Detection (warning signs):** An unknown cluster's thumbnail collage contains faces that obviously belong to an enrolled person.

**Phase/component:** `faces.py` matching logic + `face_detections` schema — Phase 1 (schema), Phase 2 (clustering gate).

---

## Notification Pitfalls

### Pitfall NOT-1: Telegram Bot Rate Limiting (30 Messages/Second Global, 20/Min Per Chat)

**What goes wrong:** If the daily digest sends one message per unknown cluster and there are 50 clusters, the bot will hit Telegram's per-chat rate limit (20 messages/minute). Telegram returns `429 Too Many Requests` with a `retry_after` field. If the code doesn't handle this, messages are silently dropped.

**Why it happens:** The naive implementation loops over clusters and calls `bot.send_photo()` in a tight loop.

**Consequences:** The user receives only the first 20 clusters and never knows the rest were dropped. Security-relevant notifications are lost.

**Prevention:**
- **Always send a single summary message** first: "📋 Daily digest: 3 new unknown persons, 12 appearances. Details below." Then send individual cluster cards.
- Implement exponential backoff with `retry_after` header parsing for all Telegram API calls.
- Use `asyncio.sleep(1)` between messages as a courtesy throttle (keeps you well under the 20/min limit even without explicit handling).
- Better yet: send one consolidated message with the top-N clusters inline (Telegram allows up to 10 photos in an album via `send_media_group`). For a family security system, 1 album message is better UX than 50 individual messages.
- Cap the daily digest to the **top 10 clusters by face count** to bound maximum message volume.

**Detection (warning signs):** Telegram logs show `429` responses. Users report receiving partial digests.

**Phase/component:** Telegram notifier service / n8n workflow — Phase 2.

---

### Pitfall NOT-2: Telegram Image Size Limits (10 MB for Photos, 50 MB for Documents)

**What goes wrong:** Telegram's `sendPhoto` API rejects images larger than 10 MB. Frame thumbnails extracted at full 1080p quality (`-q:v 2`) can be 300–500 KB each — fine individually. But if the code sends the full frame instead of a cropped face thumbnail, or sends a JPEG at quality 95, file sizes balloon. Worse: if someone passes a full 4K video frame (3–5 MB) as the notification image, Telegram silently fails or returns an error.

**Why it happens:** The notification code grabs the `minio_key` of the frame and streams it directly to Telegram without resizing.

**Consequences:** Notification image silently fails; the message arrives with no photo, which is confusing and useless for identifying an unknown visitor.

**Prevention:**
- Generate a **face crop thumbnail** at enrollment and at cluster creation time: crop the face bounding box, add 20% padding, resize to 200×200px. Store this in MinIO as `thumbnails/{cluster_id}/thumb.jpg`. This is what gets sent to Telegram.
- Enforce max image size before sending: if the thumbnail is > 1 MB, re-compress to JPEG quality 75.
- Use `send_media_group` for albums (max 10 items) to group cluster cards efficiently.

**Detection (warning signs):** Telegram messages arrive without images. Check bot's `getUpdates` or webhook logs for `400 Bad Request` with `PHOTO_INVALID_DIMENSIONS` or similar.

**Phase/component:** Thumbnail generation in ingestion pipeline + Telegram notifier — Phase 2.

---

### Pitfall NOT-3: Notification Fatigue from Over-Alerting

**What goes wrong:** If every nightly run reports all unknown faces regardless of history, the user quickly learns to ignore the digest. A neighbor who walks past the camera every morning will appear in every daily digest as "new unknown cluster" if cluster identity is not maintained (see CL-3). Within a week, the user mutes the bot.

**Why it happens:** The digest sends "unknown clusters that appeared in the last 24h" without tracking which clusters are "new vs. recurring."

**Consequences:** The core value proposition collapses — the system was supposed to surface genuinely unfamiliar faces.

**Prevention:**
- Track `first_seen_at` and `last_seen_at` on `unknown_clusters`. The Telegram digest should only alert on clusters where `first_seen_at > NOW() - 24h` (i.e., **truly new** clusters, not recurring ones).
- For recurring known unknowns (e.g., regular delivery driver), provide a UI action "Dismiss / Mark as expected" that suppresses future alerts for that cluster.
- Show the count of recurring-unknown appearances as a low-priority footnote, not a headline alert.

**Detection (warning signs):** The same cluster UUID appears in every daily digest. User complaints about repetitive notifications.

**Phase/component:** Digest query logic + `unknown_clusters.suppress_alerts` flag — Phase 2.

---

### Pitfall NOT-4: Telegram Bot Token in Docker Logs / Environment

**What goes wrong:** The Telegram bot token is stored in an env var and logged at startup ("Config loaded: TELEGRAM_TOKEN=12345:ABC..."). Any log aggregator or `docker logs` output then exposes the token.

**Why it happens:** Generic "log all config on startup" debug pattern.

**Consequences:** If the server is breached or logs are exposed, the attacker can send messages as your bot or read your chat history.

**Prevention:**
- Never log secrets. Use a `SecretStr` type (Pydantic v2 has this built in) that redacts when printed.
- Validate token format at startup (must match `\d+:[A-Za-z0-9_-]{35}`) without logging the value.
- Store the token in Docker Secrets or at minimum a `.env` file with `0600` permissions, not in `docker-compose.yml`.

**Detection (warning signs):** `docker logs ingestion-worker 2>&1 | grep TELEGRAM` returns a token.

**Phase/component:** `config.py` — Phase 1 (before any token is ever used).

---

## Storage / Scale Pitfalls

### Pitfall SS-1: pgvector HNSW Index Degradation at 10k+ Embeddings

**What goes wrong:** pgvector's HNSW implementation uses default parameters `m=16, ef_construction=64`. At 10,000–50,000 512-dim embeddings, the HNSW graph maintains good recall (~0.95). However, if rows are bulk-deleted and re-inserted (e.g., re-ingesting a video clears old `face_detections` and creates new ones), the HNSW graph develops "orphaned" nodes — nodes referenced in the graph that no longer exist in the heap. PostgreSQL's HNSW implementation in pgvector handles this via dead-node skipping, but recall can degrade subtly.

**Why it happens:** Deletes in HNSW are expensive. pgvector marks nodes as deleted but keeps them in the graph until `VACUUM` + index rebuild. High delete rates produce a bloated, lower-quality index.

**Consequences:** Nearest-neighbor queries return wrong results (missed matches) without any error — the system silently fails to find known persons.

**Prevention:**
- After re-ingesting a video (delete old `face_detections`, insert new ones), run `REINDEX INDEX CONCURRENTLY face_detections_embedding_idx` as a maintenance step. Schedule this as a weekly cron if re-ingestion is common.
- Tune HNSW parameters for 512-dim vectors: `m=32, ef_construction=128` gives much better recall at modest storage cost. For a family security system with ≤ 100k embeddings this is completely affordable.
- Set `hnsw.ef_search=64` (the query-time parameter) via `SET hnsw.ef_search=64` per connection or globally in `postgresql.conf`. Default is 40, which is too low for 512-dim at recall requirements.
- Monitor recall by periodically querying a known enrollment embedding against `person_embeddings` and verifying it returns itself as the top result with similarity > 0.99.

**Detection (warning signs):** A known person stops being recognized even though their enrollment embeddings are in the DB. Running a direct SQL similarity query (no index) returns the correct result but the HNSW-indexed query doesn't.

**Phase/component:** `db/init/001_schema.sql` (index params), weekly maintenance cron — Phase 1 (schema), Phase 3 (maintenance).

---

### Pitfall SS-2: MinIO Frame Storage Unbounded Growth

**What goes wrong:** At 1 fps + scene changes, a 1-hour 1080p video produces ~3,600–5,000 JPEG frames at ~150–300 KB each = 540 MB–1.5 GB per hour of footage. For a home security system with 24/7 cameras, this grows to 13–36 GB per day per camera. MinIO on the same Ubuntu host will exhaust disk within days.

**Why it happens:** Frames are extracted and uploaded to MinIO but never pruned. The system only stores the MinIO key in the DB — you can't tell from the DB which frames are stale.

**Consequences:** MinIO disk fills, MinIO stops accepting new objects, ingestion fails silently with "no space left on device" errors in the MinIO container.

**Prevention:**
- Define a **frame retention policy** from Day 1: frames older than N days are deleted from MinIO (but their DB records are kept — the `minio_key` simply 404s). The search UI must handle missing thumbnails gracefully (show a placeholder).
- Implement the retention job as a cron: query `frames JOIN videos WHERE videos.recorded_at < NOW() - INTERVAL '30 days'` and delete the MinIO objects.
- Alternatively (preferred): don't store frames in MinIO at all for low-confidence frames. Only upload frames that have at least one detection (YOLO confidence ≥ 0.5 or any face). This reduces frame storage by 60–80% for typical home footage.
- For the initial import of an existing video library, run a capacity estimate before processing: `total_videos_hours × 1.2 GB` = expected MinIO frame storage. Confirm disk space is available.

**Detection (warning signs):** `mc du minio/frames` output grows unboundedly. `df -h` on MinIO host shows < 10% free.

**Phase/component:** Frame extraction in `frames.py` + MinIO retention cron — Phase 1 (selective storage), Phase 3 (retention policy).

---

### Pitfall SS-3: Missing Presigned URL Expiry on Frame Thumbnails

**What goes wrong:** The API returns presigned MinIO URLs for frame thumbnails (`GET /frames/{id}/image` → 302 redirect). MinIO presigned URLs have a default expiry of 7 days. If the React UI caches these URLs (via React Query), users clicking a search result from last week will get a 403 from MinIO (URL expired) without understanding why.

**Why it happens:** MinIO presigned URL expiry is not obvious; the 302 redirect pattern hides the expiry from the frontend.

**Consequences:** Search results appear to load (the UI shows the grid), but thumbnails are broken image icons. Users think the system is broken.

**Prevention:**
- Generate presigned URLs with a **short TTL (1 hour)** for search results. The React Query cache should have a `staleTime` that matches or is shorter than the URL TTL.
- Add `Cache-Control: no-store` or a very short `max-age` on the 302 response from the API — force the frontend to re-request the presigned URL rather than caching the redirect target.
- Alternatively, proxy thumbnails through the API (`GET /frames/{id}/image` streams the bytes from MinIO, returns them as `Content-Type: image/jpeg`) — this avoids presigned URL expiry issues entirely at the cost of API bandwidth.

**Detection (warning signs):** Broken image icons in search results. Browser network tab shows 403 responses to MinIO URLs.

**Phase/component:** `frames.py` router, React Query `staleTime` config — Phase 1 (API) + Phase 2 (UI).

---

## Docker / Infrastructure Pitfalls

### Pitfall DI-1: Model Downloads at Container Startup (First-Run Cold Start)

**What goes wrong:** `YOLOv8` downloads `yolov8n.pt` (~6 MB) on first use. InsightFace downloads and extracts `buffalo_l` (~300 MB, multiple ONNX files) from the internet on first `FaceAnalysis.prepare()` call. This download happens **inside the container at runtime**, not at build time. If the download fails mid-run (network blip), the model directory is partially populated. On the next restart, InsightFace may find partial files and either silently use them (producing garbage embeddings) or throw an opaque error.

**Why it happens:** InsightFace's model downloader does not validate checksums by default. YOLOv8 download is also done at first use.

**Consequences:** Container starts, appears healthy, but produces invalid embeddings for the entire batch. The issue may not be noticed for days.

**Prevention:**
- **Download models at Docker build time**, not runtime. In the Dockerfile:
  ```dockerfile
  RUN python -c "from insightface.app import FaceAnalysis; \
      app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
      app.prepare(ctx_id=0, det_size=(640,640))"
  RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
  ```
  This bakes the models into the image layer (or into the build-time cache volume).
- Mount a `model-cache` named volume (already in requirements.md) but also validate model file presence and checksum at startup before accepting any work.
- Add a health check that verifies model files exist: `test -f /root/.cache/insightface/models/buffalo_l/det_10g.onnx`.

**Detection (warning signs):** Container logs show `Downloading model from...` after deployment. `docker inspect` shows container healthy but first real job fails with file-not-found.

**Phase/component:** `Dockerfile` for ingestion-worker — Phase 1, Day 1.

---

### Pitfall DI-2: `depends_on` Does Not Wait for PostgreSQL to Be Ready

**What goes wrong:** Docker Compose `depends_on: [postgres]` only waits for the PostgreSQL **container to start**, not for PostgreSQL to be ready to accept connections. The `ingestion-worker` and `api` services start, immediately try to connect to the DB, get "connection refused" or "the database system is starting up," and crash. Docker Compose restarts them, but if `restart: unless-stopped` is not set, they stay dead.

**Why it happens:** This is a well-known Docker Compose limitation that many developers hit for the first time.

**Consequences:** On a fresh deploy or after a host reboot, all services fail to start and require manual intervention.

**Prevention:**
- Use `depends_on` with a `condition: service_healthy` and add a health check to the postgres service:
  ```yaml
  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U videosearch -d videosearch"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
  ```
  Then in ingestion-worker and api:
  ```yaml
  depends_on:
    postgres:
      condition: service_healthy
  ```
- Additionally, implement **retry logic in the application**: on startup, retry the DB connection up to 10 times with 2s sleep between attempts. This handles edge cases where Postgres is healthy but migrations haven't run yet.

**Detection (warning signs):** After `docker compose up`, `docker logs api` shows `Connection refused` or `FATAL: database does not exist` then the container exits. Works fine after a `docker compose restart api`.

**Phase/component:** `docker-compose.yml` — Phase 1, Day 1.

---

### Pitfall DI-3: Schema Migrations Not Applied at Startup

**What goes wrong:** The schema is in `db/init/001_schema.sql` which is only executed by PostgreSQL's `docker-entrypoint-initdb.d` on **first init** (when the data volume is empty). After adding a new column (e.g., `videos.error_message`, `face_detections.low_confidence`) in a later phase, the SQL file is updated but the already-initialized volume does not re-run the init scripts. The application starts with the new code but the old schema and immediately fails with `column does not exist`.

**Why it happens:** PostgreSQL's init scripts are a "first run only" feature, not a migration system.

**Consequences:** Upgrading to a new version of the application requires either manually running ALTER TABLE or destroying the database volume.

**Prevention:**
- Use **Alembic** (the standard Python migration tool for SQLAlchemy) from Phase 1. Even if you start with raw SQL, structure it so migrations are versioned files in `db/migrations/`.
- Alternatively, use a simple custom startup script: a Python function that runs on `api` and `ingestion-worker` startup that checks `schema_version` table and applies any pending SQL patches in order.
- At minimum: add a `docker-entrypoint.sh` to each service that runs `psql -f /migrations/002_add_error_message.sql` idempotently (using `IF NOT EXISTS` or `DO $$ ... IF NOT EXISTS`).
- Never rely on `docker-entrypoint-initdb.d` alone after the initial deploy.

**Detection (warning signs):** After adding a column: `docker logs api` shows `column "error_message" of relation "videos" does not exist`. Running `docker compose down -v && docker compose up` fixes it (because it reinitializes the DB) but loses all data.

**Phase/component:** `db/` — Phase 1. Establish migration tooling before any schema changes are needed.

---

### Pitfall DI-4: Ingestion Worker Zombie Jobs After Restart

**What goes wrong:** If the ingestion-worker container is killed (OOM, restart, deploy) while a video is `status = 'processing'`, the video is permanently stuck in that state. On the next start, the worker doesn't re-queue it because the idempotency check sees `processing` (not `done`) and skips it (or, if it doesn't check for `processing`, it tries to process it again and creates duplicate rows).

**Why it happens:** The state machine has no "recover from crash" transition.

**Consequences:** Videos are silently skipped forever. The user can only unstick them by manually updating the DB.

**Prevention:**
- On ingestion-worker startup, run a recovery query:
  ```sql
  UPDATE videos SET status = 'pending', error_message = 'Recovered from crash'
  WHERE status = 'processing' AND ingested_at < NOW() - INTERVAL '1 hour';
  ```
  This resets stuck jobs. The 1-hour buffer prevents concurrent workers from resetting each other's active jobs.
- Add `?force=true` to the ingest API to allow manual re-queuing from the UI.
- Store a `worker_heartbeat_at` timestamp on in-progress videos so the recovery query can use a real heartbeat timeout instead of a fixed interval.

**Detection (warning signs):** `SELECT * FROM videos WHERE status = 'processing'` returns rows that haven't been updated in hours. `docker logs ingestion-worker` shows no activity for those video IDs.

**Phase/component:** `main.py` startup + `pipeline.py` — Phase 1 acceptance criterion (requirement already noted in requirements.md §11).

---

### Pitfall DI-5: External Docker Network Not Pre-Created

**What goes wrong:** The requirements correctly note that MinIO and n8n run in a separate compose stack and must be referenced via an `external` Docker network. If that network doesn't exist when `docker compose up` runs, Docker Compose exits with `network not found` before starting any container.

**Why it happens:** External networks must be created manually or by the other compose stack. If the other stack hasn't been started first, or the network name has changed, this fails silently at deploy time.

**Consequences:** First deploy fails with a cryptic Docker network error. The developer spends time debugging what looks like a configuration problem.

**Prevention:**
- Document the exact network name and creation command in `README.md`:
  ```bash
  docker network create home-infra  # or whatever the existing network is named
  ```
- Add a `Makefile` target `make network` that creates the network idempotently (`docker network create home-infra || true`).
- In `docker-compose.yml`, declare the external network with an explicit name to avoid any ambiguity:
  ```yaml
  networks:
    home-infra:
      external: true
      name: home-infra
  ```
- Add a pre-flight check script (`scripts/preflight.sh`) that validates the external network exists before attempting `docker compose up`.

**Detection (warning signs):** `docker compose up` immediately exits with `network home-infra declared as external, but could not be found`.

**Phase/component:** `docker-compose.yml` + `README.md` — Phase 1, Day 1.

---

## Phase-Specific Warning Summary

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|---------------|------------|
| Phase 1 | InsightFace integration | Using `face.embedding` instead of `face.normed_embedding` (FR-4) | Defensive normalize utility, unit test |
| Phase 1 | Face match threshold | 0.5 is too low, causes false positives (FR-1) | Start at 0.65, validate on real footage |
| Phase 1 | Memory during batch | YOLO + InsightFace simultaneous = OOM (MEM-1) | Sequential pipeline, OMP_NUM_THREADS=2 |
| Phase 1 | FFmpeg frame extraction | All frames to disk before processing (MEM-2) | Sliding window / streaming approach |
| Phase 1 | Docker startup | depends_on not waiting for DB ready (DI-2) | service_healthy condition + app-level retry |
| Phase 1 | Model downloads | Downloaded at runtime, partial failures (DI-1) | Bake into Docker build step |
| Phase 1 | Zombie jobs | Crash during processing leaves status='processing' (DI-4) | Recovery query at startup |
| Phase 1 | Schema evolution | No migration tooling (DI-3) | Add Alembic from day 1 |
| Phase 1 | HNSW params | Default m=16 is suboptimal for 512-dim (SS-1) | Set m=32, ef_construction=128, ef_search=64 |
| Phase 2 | Unknown clustering | DBSCAN OOM at scale (CL-1) | Use HDBSCAN or pgvector incremental approach |
| Phase 2 | Cluster epsilon | Too high → 1 giant cluster (CL-2) | Validate on real footage, start at ε=0.40 |
| Phase 2 | Cluster drift | Re-clustering loses user labels (CL-3) | Incremental clustering, stable UUIDs |
| Phase 2 | Known faces in cluster pool | Below-threshold known faces cluster as unknown (CL-4) | Two-tier threshold, probable_person_id |
| Phase 2 | Telegram rate limit | 50 messages → 429 errors (NOT-1) | Single album message, top-10 cap |
| Phase 2 | Telegram image size | Full frames > 10 MB rejected (NOT-2) | Generate face-crop thumbnails |
| Phase 2 | Notification fatigue | Recurring strangers alert every day (NOT-3) | first_seen_at tracking, suppress flag |
| Phase 3 | MinIO growth | Unbounded frame storage (SS-2) | Selective storage (detections only) + retention cron |
| Phase 3 | HNSW index health | Delete-heavy workloads degrade recall (SS-1) | Weekly REINDEX CONCURRENTLY |
| Ongoing | Presigned URL expiry | Cached URLs expire, broken thumbnails (SS-3) | Short TTL + matching React Query staleTime |

---

## Sources

- InsightFace GitHub issues and documentation: known behavior of `normed_embedding` vs `embedding`, `buffalo_l` accuracy characteristics
- pgvector documentation: HNSW index parameters (`m`, `ef_construction`, `hnsw.ef_search`), delete behavior, bulk insert recommendations
- ArcFace paper (Deng et al., 2019): threshold sensitivity to image quality and lighting
- HDBSCAN documentation: memory-efficient clustering for high-dimensional embeddings
- Telegram Bot API documentation: rate limits (30 messages/second global, 20 messages/minute per chat), `sendPhoto` 10 MB limit, `sendMediaGroup` batch API
- Docker Compose documentation: `depends_on` service_healthy condition behavior
- Known ONNX Runtime behavior: thread contention with `OMP_NUM_THREADS`, memory allocation patterns on CPU providers
- Community post-mortems on self-hosted face recognition systems (Frigate, DeepFace, CompreFace) for clustering and threshold pitfall patterns
- **Confidence: HIGH** for InsightFace, pgvector, Docker Compose, and Telegram pitfalls (all well-documented). **MEDIUM** for HDBSCAN epsilon tuning on security footage (domain-specific, fewer public references for this exact setup).
