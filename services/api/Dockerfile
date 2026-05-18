FROM python:3.11-slim-bookworm

# System dependencies: build tools for insightface C extensions + runtime libs.
# Mirrors ingestion-worker/Dockerfile exactly.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /app

# Pre-install insightface build-time deps BEFORE full requirements.txt.
# insightface==0.7.3 compiles Cython extensions — cython + numpy must exist first.
RUN uv pip install --system --no-cache "cython" "numpy<2.0"

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app/ ./app/

# ── Bake InsightFace buffalo_l model at build time ────────────────────────────
# Downloads ~280 MB (SCRFD-10G + ArcFace R100) → ~/.insightface/models/buffalo_l/
# Build fails fast if model download fails (no silent fallback to runtime download).
RUN python -c "\
from insightface.app import FaceAnalysis; \
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider']); \
app.prepare(ctx_id=0, det_size=(640, 640)); \
print('InsightFace buffalo_l baked successfully')"
# ─────────────────────────────────────────────────────────────────────────────

# ONNX Runtime thread count for i5-6200 (dual-core, 4 HT threads)
ENV OMP_NUM_THREADS=4
ENV ONNX_DISABLE_GLOBAL_THREAD_POOL=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
