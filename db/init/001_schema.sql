-- HomeVideoSearcher — PostgreSQL 16 + pgvector 0.8.2
-- IMPORTANT: Run on a fresh database only. After first deploy, use Alembic migrations.
-- HNSW params: m=32, ef_construction=128 applied to all vector indexes.
-- hnsw.ef_search=64 is set at the postgres service level (docker-compose command arg).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid() fallback

-- ── Videos ──────────────────────────────────────────────────────────────────
CREATE TABLE videos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minio_key       TEXT NOT NULL UNIQUE,
    filename        TEXT NOT NULL,
    duration_sec    NUMERIC,
    width           INT,
    height          INT,
    fps             NUMERIC,
    recorded_at     TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    error_message   TEXT          -- populated on status='failed'
);
CREATE INDEX ON videos (status);
CREATE INDEX ON videos (ingested_at DESC);

-- ── Frames ──────────────────────────────────────────────────────────────────
-- Only frames with at least one detection (YOLO or face) are stored.
CREATE TABLE frames (
    id              BIGSERIAL PRIMARY KEY,
    video_id        UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    ts_ms           INT NOT NULL,                   -- ms from start of video
    minio_key       TEXT NOT NULL,                  -- "frames/{video_id}/{ts_ms}.jpg"
    UNIQUE (video_id, ts_ms)
);
CREATE INDEX ON frames (video_id, ts_ms);

-- ── Detections (YOLO output) ─────────────────────────────────────────────────
CREATE TABLE detections (
    id              BIGSERIAL PRIMARY KEY,
    frame_id        BIGINT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    class_name      TEXT NOT NULL,
    confidence      REAL NOT NULL,
    bbox_x1         INT,
    bbox_y1         INT,
    bbox_x2         INT,
    bbox_y2         INT
);
CREATE INDEX ON detections (frame_id);
CREATE INDEX ON detections (class_name);

-- ── Known persons (enrollment) ───────────────────────────────────────────────
CREATE TABLE known_persons (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- One row per enrollment image. Multiple embeddings per person for robustness.
-- Column is named normed_embedding (not embedding) to enforce correct field access.
CREATE TABLE person_embeddings (
    id                  BIGSERIAL PRIMARY KEY,
    person_id           UUID NOT NULL REFERENCES known_persons(id) ON DELETE CASCADE,
    normed_embedding    vector(512) NOT NULL,        -- InsightFace face.normed_embedding
    source_image        TEXT,                        -- MinIO key of source enrollment photo
    created_at          TIMESTAMPTZ DEFAULT now()
);
-- HNSW index: m=32, ef_construction=128 (not pgvector defaults m=16)
CREATE INDEX person_embeddings_hnsw_idx
    ON person_embeddings
    USING hnsw (normed_embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 128);

-- ── Unknown face clusters (stable UUIDs — Phase 3 populates this) ────────────
-- Created here so face_detections.unknown_cluster_id FK is valid from day 1.
-- Populated by POST /cluster/run (Phase 3). Never truncated and rewritten
-- — cluster UUIDs are stable across nightly runs.
CREATE TABLE unknown_clusters (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    representative_face_id  BIGINT,             -- FK set after face_detections created
    appearance_count        INT NOT NULL DEFAULT 0,
    first_seen              TIMESTAMPTZ,
    last_seen               TIMESTAMPTZ,
    label                   TEXT,               -- user-assigned label ("Delivery person")
    created_at              TIMESTAMPTZ DEFAULT now()
);

-- ── Face detections (InsightFace output) ─────────────────────────────────────
-- match_tier: 'confident' (>=0.65), 'probable' (0.50-0.65), NULL (unknown/unmatched)
-- unknown_cluster_id: set by Phase 3 clustering job; NULL until then
CREATE TABLE face_detections (
    id                  BIGSERIAL PRIMARY KEY,
    frame_id            BIGINT NOT NULL REFERENCES frames(id) ON DELETE CASCADE,
    bbox_x1             INT,
    bbox_y1             INT,
    bbox_x2             INT,
    bbox_y2             INT,
    det_score           REAL,                   -- SCRFD face detector confidence
    normed_embedding    vector(512) NOT NULL,   -- ArcFace normed_embedding (L2-normalized)
    matched_person_id   UUID REFERENCES known_persons(id) ON DELETE SET NULL,
    match_similarity    REAL,                   -- cosine similarity to best match
    match_tier          TEXT CHECK (match_tier IN ('confident', 'probable')),
    unknown_cluster_id  UUID REFERENCES unknown_clusters(id) ON DELETE SET NULL
);
-- HNSW index: m=32, ef_construction=128
CREATE INDEX face_detections_hnsw_idx
    ON face_detections
    USING hnsw (normed_embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 128);
CREATE INDEX ON face_detections (frame_id);
CREATE INDEX ON face_detections (matched_person_id);
CREATE INDEX ON face_detections (unknown_cluster_id);
CREATE INDEX ON face_detections (match_tier);

-- Back-reference: unknown_clusters -> its representative face
-- Added after face_detections to avoid forward FK reference
ALTER TABLE unknown_clusters
    ADD CONSTRAINT fk_representative_face
    FOREIGN KEY (representative_face_id)
    REFERENCES face_detections(id)
    ON DELETE SET NULL;
