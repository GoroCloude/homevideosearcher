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
