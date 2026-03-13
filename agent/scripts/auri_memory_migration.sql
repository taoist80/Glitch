-- Idempotent auri_memory migration for Protect RDS.
-- Run manually if the runtime never connects (Protect not configured) or to verify the table.
-- Requires: PostgreSQL 15+ with pgvector (CREATE EXTENSION vector by rds_superuser if needed).
--
-- Usage:
--   psql "$GLITCH_PROTECT_DB_URI" -f agent/scripts/auri_memory_migration.sql
-- Or with IAM token: set PGPASSWORD to rds generate-db-auth-token output, then run this file.

CREATE TABLE IF NOT EXISTS auri_memory (
    memory_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT NOT NULL,
    embedding   vector(1024) NOT NULL,
    session_id  TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT 'agent',
    metadata    JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auri_memory_embedding
    ON auri_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_auri_memory_created_at
    ON auri_memory (created_at DESC);
