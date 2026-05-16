FROM python:3.11-slim-bookworm

# System dependencies: FFmpeg for frame extraction, libGL for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager (faster than pip; pinned version)
RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /app

# Install Python dependencies via uv
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy application code
COPY app/ ./app/

# ── Bake ML models at build time ──────────────────────────────────────────────
# YOLO model (~6 MB weights for yolov8n.pt) → ~/.cache/ultralytics/
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt'); print('YOLO baked')"

# InsightFace buffalo_l (~280 MB: SCRFD-10G + ArcFace R100) → ~/.insightface/models/
RUN python -c "
from insightface.app import FaceAnalysis
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))
print('InsightFace buffalo_l baked successfully')
"
# ─────────────────────────────────────────────────────────────────────────────

# ONNX Runtime thread count for i5-6200 (dual-core, 4 HT threads)
ENV OMP_NUM_THREADS=4
ENV ONNX_DISABLE_GLOBAL_THREAD_POOL=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
