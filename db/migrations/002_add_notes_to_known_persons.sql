-- Phase 2 migration: add optional notes field to known_persons.
-- Safe to run multiple times (IF NOT EXISTS guard).
ALTER TABLE known_persons
    ADD COLUMN IF NOT EXISTS notes TEXT;
