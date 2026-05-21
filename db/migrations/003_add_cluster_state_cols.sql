-- Phase 3 migration: add ignored + promoted_at state columns to unknown_clusters.
-- Safe to run multiple times (IF NOT EXISTS guard on ADD COLUMN and CREATE INDEX).
ALTER TABLE unknown_clusters
    ADD COLUMN IF NOT EXISTS ignored     BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS unknown_clusters_ignored_idx ON unknown_clusters (ignored);
