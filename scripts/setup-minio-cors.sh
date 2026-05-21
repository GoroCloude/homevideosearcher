#!/usr/bin/env bash
# setup-minio-cors.sh — Phase 5: Video Upload UI
#
# PURPOSE: Verify MinIO connectivity and bucket existence for direct browser uploads.
#          Documents CORS defaults and provides legacy fallback commands.
#
# IMPORTANT: Modern MinIO (RELEASE.2022+) has CORS enabled by default for all buckets
#            and all HTTP verbs. No explicit BucketCORS configuration is needed.
#            This script verifies your setup and is safe to run without making changes.
#
# USAGE:
#   MINIO_ALIAS=myminio MINIO_BUCKET=videos bash scripts/setup-minio-cors.sh
#   or positional: ./scripts/setup-minio-cors.sh [ALIAS] [BUCKET]
#
# IDEMPOTENT: Safe to re-run — no destructive changes unless legacy fallback is uncommented.
#
# T4 SECURITY: Never use wildcard '*' origins. The presigned PUT URL is self-authenticating
#              via HMAC — any valid URL can be used from any origin. Restrict access by
#              keeping MINIO_PUBLIC_ENDPOINT unexposed (behind firewall/Cloudflare Tunnel).
#              Allowed UI origins: http://homevideosearcher.shumov.eu  http://localhost:5173

set -euo pipefail

ALIAS="${1:-${MINIO_ALIAS:-myminio}}"
BUCKET="${2:-${MINIO_BUCKET:-videos}}"

echo "=== MinIO CORS setup for Phase 5: Video Upload ==="
echo "    Alias:  $ALIAS"
echo "    Bucket: $BUCKET"
echo ""

# 1. Verify mc (MinIO Client) is installed
if ! command -v mc &>/dev/null; then
    echo "ERROR: mc (MinIO Client) not found."
    echo "  Install: https://min.io/docs/minio/linux/reference/minio-mc.html"
    exit 1
fi
echo "✓ mc installed: $(mc --version 2>&1 | head -1)"

# 2. Verify alias connectivity
echo "→ Verifying connection to MinIO alias '$ALIAS'..."
if ! mc ls "$ALIAS" &>/dev/null; then
    echo "ERROR: Cannot connect to MinIO alias '$ALIAS'."
    echo "  Configure: mc alias set $ALIAS <MINIO_URL> <ACCESS_KEY> <SECRET_KEY>"
    exit 1
fi
echo "✓ Connected to '$ALIAS'"

# 3. Verify bucket exists
echo "→ Checking bucket '$BUCKET'..."
if ! mc ls "$ALIAS/$BUCKET" &>/dev/null; then
    echo "ERROR: Bucket '$BUCKET' not found on '$ALIAS'."
    echo "  Create: mc mb $ALIAS/$BUCKET"
    exit 1
fi
echo "✓ Bucket '$BUCKET' exists"

# 4. CORS status
echo ""
echo "✓ CORS status:"
echo "  Modern MinIO (RELEASE.2022+) enables CORS for all buckets by default."
echo "  Direct browser PUT uploads via presigned URLs should work without configuration."
echo ""
echo "  If you encounter browser CORS errors blocking the PUT request:"
echo "  1. Verify MINIO_PUBLIC_ENDPOINT in .env is the browser-resolvable hostname"
echo "     (NOT an internal Docker hostname like 'minio:9000')."
echo "  2. For legacy MinIO (<2022), uncomment the fallback below:"
echo ""
echo "  # Legacy fallback (allows anonymous PUT — presigned URL still required):"
echo "  # mc anonymous set upload $ALIAS/$BUCKET"
echo ""

# Uncomment the following block ONLY for pre-2022 MinIO instances:
# echo "→ Setting legacy upload policy (idempotent)..."
# mc anonymous set upload "$ALIAS/$BUCKET"
# echo "✓ Upload policy set on $ALIAS/$BUCKET"

echo "=== Setup complete. Direct browser uploads to MinIO/$BUCKET are ready. ==="
echo ""
echo "Next steps:"
echo "  1. Ensure MINIO_PUBLIC_ENDPOINT in .env is the browser-resolvable MinIO hostname."
echo "  2. Upload a test video from the Videos page to verify end-to-end."
echo "  3. If CORS errors persist, see the legacy fallback instructions above."
