# Plan 03: n8n Workflows & Ingestion-Worker Defense

**Phase:** 02 - Enrollment, Search API & n8n Automation  
**Goal:** Harden `POST /ingest` against non-video files, create exportable n8n workflow JSONs for event-driven and polling-based video ingestion, and document the MinIO webhook configuration — so new camera recordings automatically trigger ingestion within 60 seconds of upload.

**Requirements covered:** N8N-01, N8N-02  
**Depends on:** Phase 1 complete (ingestion-worker running with `POST /ingest` and `POST /ingest/batch`)  
**Wave:** 1 (only modifies ingestion-worker + creates new docs files; no api files touched)

---

## Tasks

### Task 1 — Add video extension guard to `POST /ingest` in ingestion-worker

**File:** `services/ingestion-worker/app/main.py` *(modify)*

The MinIO webhook fires for ALL `s3:ObjectCreated:*` events, including `.jpg`, `.txt`, and any other file put into the `videos/` bucket path. Without a guard, the worker will attempt to ingest a non-video file, fail FFmpeg extraction, and mark it as `failed` — polluting the DB.

**Changes required:**

1. Add `HTTPException` to the fastapi import line:
   ```python
   # Before:
   from fastapi import BackgroundTasks, FastAPI, Query
   # After:
   from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
   ```

2. Add `Path` import from pathlib — it is already imported at the top of ingestion-worker if used elsewhere; if not present, add:
   ```python
   from pathlib import Path
   ```
   *(Check the existing file — `Path` may already be imported in `pipeline.py` or `frames.py` but not `main.py`. Add it to `main.py` if missing.)*

3. In the `ingest()` endpoint function, add the extension guard immediately after the `filename = ...` line (before the DB lookup):
   ```python
   @app.post("/ingest", response_model=IngestResponse, status_code=202)
   async def ingest(
       request: IngestRequest,
       background_tasks: BackgroundTasks,
       force: bool = Query(False, description="Re-process even if status=done"),
   ) -> IngestResponse:
       minio_key = request.minio_key.strip()
       filename = minio_key.split("/")[-1]

       # ── Defensive extension filter ────────────────────────────────────────
       # Guard against MinIO webhook firing for non-video uploads
       # (e.g., thumbnails, motion-detection images, config files).
       _VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
       _ext = Path(filename).suffix.lower()
       if _ext not in _VIDEO_EXTENSIONS:
           raise HTTPException(
               status_code=422,
               detail=(
                   f"Unsupported file type '{_ext}'. "
                   f"Accepted: {', '.join(sorted(_VIDEO_EXTENSIONS))}"
               ),
           )
       # ─────────────────────────────────────────────────────────────────────

       # (rest of the existing function unchanged)
   ```

**Verify:** `curl -X POST http://localhost:8001/ingest -H "Content-Type: application/json" -d '{"minio_key":"videos/test.jpg"}'` returns HTTP 422 with detail `"Unsupported file type '.jpg'..."`.

---

### Task 2 — Create n8n workflow JSON: event-driven ingest

**File:** `docs/n8n-minio-ingest-workflow.json` *(create new)*

Import this file into n8n via **Settings → Import from file**.

The workflow fires when MinIO posts an `s3:ObjectCreated:*` event to the n8n Webhook node, extracts the object key, filters non-video files, and calls `POST /ingest` on the ingestion-worker.

```json
{
  "name": "MinIO Video Ingest (Event-Driven)",
  "nodes": [
    {
      "parameters": {
        "httpMethod": "POST",
        "path": "minio-ingest",
        "responseMode": "onReceived",
        "responseData": "noData",
        "options": {}
      },
      "id": "b1e2c3d4-0001-0001-0001-000000000001",
      "name": "MinIO Webhook",
      "type": "n8n-nodes-base.webhook",
      "typeVersion": 2,
      "position": [240, 300],
      "webhookId": "minio-ingest-webhook-v1"
    },
    {
      "parameters": {
        "jsCode": "// Extract the MinIO object key from the S3-compatible event payload.\n// MinIO sends two payload shapes; handle both:\n//   Shape A (top-level Key field): { \"Key\": \"videos/cam01/clip.mp4\", ... }\n//   Shape B (Records array, S3-compatible): { \"Records\": [{ \"s3\": { \"object\": { \"key\": \"...\" } } }] }\nconst body = $input.first().json.body || $input.first().json;\nconst key = body.Key || (body.Records && body.Records.length > 0 && body.Records[0].s3 && body.Records[0].s3.object && body.Records[0].s3.object.key);\n\nif (!key) {\n  // Payload did not contain a recognisable object key — skip silently\n  return [];\n}\n\n// Extension filter — same set as ingestion-worker defensive guard\nconst VIDEO_EXTS = /\\.(mp4|mov|avi|mkv)$/i;\nif (!VIDEO_EXTS.test(key)) {\n  // Not a video file — skip (no HTTP call made)\n  return [];\n}\n\nreturn [{ json: { minio_key: key } }];"
      },
      "id": "b1e2c3d4-0002-0002-0002-000000000002",
      "name": "Extract & Filter Key",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [460, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://ingestion-worker:8001/ingest",
        "sendBody": true,
        "contentType": "json",
        "body": "={{ JSON.stringify({ minio_key: $json.minio_key }) }}",
        "options": {
          "timeout": 10000
        }
      },
      "id": "b1e2c3d4-0003-0003-0003-000000000003",
      "name": "Trigger Ingest",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [680, 300]
    }
  ],
  "connections": {
    "MinIO Webhook": {
      "main": [
        [
          {
            "node": "Extract & Filter Key",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Extract & Filter Key": {
      "main": [
        [
          {
            "node": "Trigger Ingest",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "active": false,
  "settings": {
    "executionOrder": "v1",
    "saveManualExecutions": true,
    "callerPolicy": "workflowsFromSameOwner"
  },
  "versionId": "02-n8n-event-v1"
}
```

**Note:** Set `"active": true` only after completing Task 4 (MinIO webhook target configuration) and verifying the webhook URL resolves. Import first with `active: false`, test manually using n8n's "Test workflow" button, then activate.

---

### Task 3 — Create n8n workflow JSON: polling fallback

**File:** `docs/n8n-polling-fallback-workflow.json` *(create new)*

This workflow runs every 10 minutes and calls `POST /ingest/batch` — the ingestion-worker endpoint that scans the MinIO `videos/` prefix and enqueues any `pending` or `failed` videos. It is the fallback for webhook missed events.

```json
{
  "name": "MinIO Video Ingest (Polling Fallback — every 10 min)",
  "nodes": [
    {
      "parameters": {
        "rule": {
          "interval": [
            {
              "field": "cronExpression",
              "expression": "*/10 * * * *"
            }
          ]
        }
      },
      "id": "c2f3d4e5-0001-0001-0001-000000000001",
      "name": "Every 10 Minutes",
      "type": "n8n-nodes-base.scheduleTrigger",
      "typeVersion": 1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "method": "POST",
        "url": "http://ingestion-worker:8001/ingest/batch",
        "sendBody": true,
        "contentType": "json",
        "body": "{ \"prefix\": \"videos/\", \"force\": false }",
        "options": {
          "timeout": 30000
        }
      },
      "id": "c2f3d4e5-0002-0002-0002-000000000002",
      "name": "Scan & Enqueue Videos",
      "type": "n8n-nodes-base.httpRequest",
      "typeVersion": 4,
      "position": [460, 300]
    }
  ],
  "connections": {
    "Every 10 Minutes": {
      "main": [
        [
          {
            "node": "Scan & Enqueue Videos",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "active": false,
  "settings": {
    "executionOrder": "v1",
    "saveManualExecutions": true
  },
  "versionId": "02-n8n-polling-v1"
}
```

**Note:** The `POST /ingest/batch` endpoint has built-in idempotency — it skips `done` videos. Running this every 10 minutes will never re-process a completed video unless `force: true` is passed. No auth is needed since ingestion-worker is on the internal Docker network with no exposed token.

---

### Task 4 — Create `docs/n8n-setup.md`

**File:** `docs/n8n-setup.md` *(create new)*

````markdown
# n8n Automation Setup Guide

Two n8n workflows automate video ingestion:

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| **Event-Driven** | MinIO `s3:ObjectCreated:*` webhook | Immediate ingest on upload |
| **Polling Fallback** | Schedule every 10 minutes | Catch any missed webhook events |

---

## Prerequisites

- n8n running on the `home-infra` Docker network (hostname: `n8n`, port `5678`)
- MinIO `mc` CLI configured with alias `myminio` pointing to your MinIO instance
- ingestion-worker healthy: `curl http://localhost:8001/health` returns `{"status":"ok"}`

---

## Step 1 — Import Workflows into n8n

1. Open n8n: `http://<your-host>:5678`
2. In the left sidebar click **Workflows → Import from file**
3. Import `docs/n8n-minio-ingest-workflow.json` → workflow appears as **MinIO Video Ingest (Event-Driven)**
4. Import `docs/n8n-polling-fallback-workflow.json` → workflow appears as **MinIO Video Ingest (Polling Fallback)**

> Do NOT activate either workflow yet — complete Steps 2–3 first.

---

## Step 2 — Configure MinIO Webhook Notification Target

MinIO must be told to POST event notifications to the n8n Webhook node.
The n8n webhook URL for the event-driven workflow is:
```
http://n8n:5678/webhook/minio-ingest
```

Run these commands from a host that has `mc` configured with alias `myminio`:

```bash
# 1. Register the webhook notification target in MinIO
mc admin config set myminio notify_webhook:n8n_ingest \
    endpoint="http://n8n:5678/webhook/minio-ingest" \
    queue_limit="0" \
    enable="on"

# 2. Restart MinIO to apply the new config
mc admin service restart myminio

# 3. Verify the target is registered
mc admin config get myminio notify_webhook:n8n_ingest
# Expected: endpoint=http://n8n:5678/webhook/minio-ingest enable=on
```

---

## Step 3 — Subscribe the `videos` Bucket to the Webhook

```bash
# Subscribe the videos bucket to ObjectCreated events
mc event add myminio/videos \
    arn:minio:sqs::n8n_ingest:webhook \
    --event s3:ObjectCreated:*

# Verify subscription is active
mc event list myminio/videos
# Expected output shows: s3:ObjectCreated:* → arn:minio:sqs::n8n_ingest:webhook
```

> **Note:** The `--prefix "videos/"` flag is optional. If your bucket is named `videos` and only contains video files, no prefix filter is needed. If the bucket contains mixed content, add `--prefix "videos/"` to only trigger on objects under that path prefix.

---

## Step 4 — Test the Event-Driven Workflow

```bash
# Upload a test video to MinIO
mc cp /path/to/test.mp4 myminio/videos/test.mp4

# Within 5–10 seconds, check ingestion-worker logs
docker compose logs ingestion-worker --tail=20
# Expected: "Queued video videos/test.mp4 (id=<uuid>)"

# Check video status in DB
docker compose exec postgres psql -U videosearch -d videosearch \
    -c "SELECT minio_key, status FROM videos ORDER BY ingested_at DESC LIMIT 5;"
```

If the event does not fire within 30 seconds:
1. Check n8n execution history for the workflow — look for failed executions
2. Check MinIO logs: `docker compose logs minio --tail=50` (or your MinIO container name)
3. Verify `mc event list myminio/videos` still shows the subscription (MinIO config persists across restarts but loses subscriptions on bucket re-creation)

---

## Step 5 — Activate Both Workflows

Once the manual test in Step 4 succeeds:

1. Open the **MinIO Video Ingest (Event-Driven)** workflow in n8n → toggle **Active** → **ON**
2. Open the **MinIO Video Ingest (Polling Fallback)** workflow in n8n → toggle **Active** → **ON**

The polling fallback will fire every 10 minutes automatically. Its first execution after activation will scan `videos/` and enqueue any videos already uploaded but not yet processed.

---

## Workflow Logic Reference

### Event-Driven Workflow

```
[MinIO Webhook: POST /webhook/minio-ingest]
    │
    ▼
[Code Node: Extract & Filter Key]
    • Extracts object key from MinIO S3 event payload
    • Supports both payload shapes (Key: field and Records[].s3.object.key)
    • Returns [] (skip) if key does not match .(mp4|mov|avi|mkv) extension
    │
    ▼  (only if video file)
[HTTP Request: POST http://ingestion-worker:8001/ingest]
    Body: { "minio_key": "<extracted key>" }
    Timeout: 10 s (ingest endpoint responds immediately with "queued")
```

### Polling Fallback Workflow

```
[Schedule Trigger: */10 * * * *]
    │
    ▼
[HTTP Request: POST http://ingestion-worker:8001/ingest/batch]
    Body: { "prefix": "videos/", "force": false }
    Timeout: 30 s
    • Skips already-done videos (idempotent)
    • Enqueues pending/failed videos
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Webhook fires but ingestion-worker returns 422 | File extension not in accepted set | Normal — non-video file uploaded. Check Task 1 guard is deployed. |
| Webhook not firing at all | MinIO config lost after restart | Re-run Step 2 `mc admin config set` and Step 3 `mc event add` |
| n8n can't reach `ingestion-worker:8001` | n8n not on `home-infra` network | Add `home-infra` to n8n's Docker networks |
| `mc admin config set` returns "Access Denied" | mc alias has insufficient permissions | Use the MinIO root credentials for the mc alias |
| Polling fallback enqueues but videos stay `pending` | ingestion-worker crashed or OOM | Check `docker compose ps` and restart if unhealthy |
````

---

## Verification

After executing all tasks, verify the following:

- [ ] `curl -X POST http://localhost:8001/ingest -H "Content-Type: application/json" -d '{"minio_key":"videos/test.jpg"}'` returns HTTP 422 with `"Unsupported file type '.jpg'..."`
- [ ] `curl -X POST http://localhost:8001/ingest -H "Content-Type: application/json" -d '{"minio_key":"videos/test.mp4"}'` returns HTTP 202 `{"status":"queued",...}` (as before)
- [ ] `docs/n8n-minio-ingest-workflow.json` is valid JSON: `python -c "import json; json.load(open('docs/n8n-minio-ingest-workflow.json'))"` exits 0
- [ ] `docs/n8n-polling-fallback-workflow.json` is valid JSON: same test
- [ ] Both JSON files import into n8n without error (Settings → Import from file)
- [ ] n8n event-driven workflow test: send a POST to the n8n webhook URL with a test payload → Trigger Ingest node shows status "Success" in execution history
- [ ] n8n polling fallback test: run the workflow manually once → Scan & Enqueue Videos node shows HTTP 202 response from ingestion-worker
- [ ] After completing MinIO `mc event add` setup (Step 3 of docs/n8n-setup.md): uploading a `.mp4` to the MinIO `videos/` bucket triggers the workflow within 60 seconds; video appears in `videos` table with status `processing` or `done`
- [ ] Uploading a `.jpg` to the same bucket does NOT trigger an ingest attempt (Code Node returns [] and workflow exits early)

---

## Threat Model

- **Unauthenticated webhook endpoint:** The n8n webhook `POST /webhook/minio-ingest` accepts any POST request from within the Docker network. On the `home-infra` internal network, this is intentional — MinIO does not support webhook request signing. Mitigation: the webhook is only reachable inside Docker (not exposed to internet); the ingestion-worker `POST /ingest` itself validates the `minio_key` format and extension; a forged request can only enqueue a video key that exists in MinIO (otherwise FFmpeg download fails gracefully).

- **n8n execution history stores MinIO keys:** n8n stores input/output for each workflow execution (visible in execution history). For a private self-hosted system with no PII in MinIO keys, this is acceptable. If MinIO keys encode sensitive camera names or locations: disable execution data saving in n8n workflow settings (`saveManualExecutions: false`, or set n8n's `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none` env var).

- **`POST /ingest/batch` called every 10 minutes without auth:** The ingestion-worker intentionally has no auth (internal service). The polling workflow uses no token. Risk: if ingestion-worker port 8001 is accidentally exposed to the internet, anyone can trigger batch ingestion. Mitigation: verify `ports:` in docker-compose.yml maps only to `127.0.0.1:8001:8001` (loopback) or is omitted entirely for internal-only access.

- **MinIO webhook config persistence:** `mc admin config set` writes to MinIO's config store (etcd or local file). `mc event add` writes to the bucket's event configuration. Both survive MinIO restarts. However, if the MinIO data volume is deleted and recreated, both must be re-run. Document in `docs/operations.md` (update the existing Phase 1 operations guide to reference `n8n-setup.md`).

- **n8n workflow JSON UUIDs collide across environments:** The workflow JSON contains hardcoded node IDs (`b1e2c3d4-...`). Importing into an n8n instance that already has a workflow with those IDs will prompt n8n to assign new IDs — this is expected behavior and not a security concern. The IDs are random-looking placeholders; no sensitive data is embedded.
