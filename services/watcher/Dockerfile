FROM python:3.11-slim-bookworm

# curl for healthcheck / debugging only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager (same pinned version as all services)
RUN pip install --no-cache-dir uv==0.11.14

WORKDIR /app

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.main"]
