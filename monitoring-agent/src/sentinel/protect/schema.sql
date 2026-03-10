-- UniFi Protect Integration Schema
-- Requires PostgreSQL 15+ with pgvector extension
-- Run: CREATE EXTENSION IF NOT EXISTS vector;
--      CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- CAMERAS
-- ============================================================
CREATE TABLE IF NOT EXISTS cameras (
    camera_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    location        TEXT,
    type            TEXT,
    zone            TEXT,  -- front, rear, side, garage, interior
    is_restricted   BOOLEAN DEFAULT FALSE,
    restricted_hours_start INT,  -- hour 0-23 (NULL = not restricted)
    restricted_hours_end   INT,
    adjacent_cameras TEXT[],     -- camera_ids of adjacent cameras
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- EVENTS
-- Raw Protect events with enriched analysis
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    camera_id       TEXT REFERENCES cameras(camera_id) ON DELETE SET NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    entity_type     TEXT,  -- vehicle, person, animal, package, motion
    score           FLOAT,
    anomaly_score   FLOAT DEFAULT 0.0,
    anomaly_factors JSONB DEFAULT '{}'::jsonb,
    classifications JSONB DEFAULT '{}'::jsonb,
    snapshot_url    TEXT,
    video_clip_url  TEXT,
    processed       BOOLEAN DEFAULT FALSE,
    processed_at    TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_camera_timestamp ON events(camera_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_entity_type ON events(entity_type);
CREATE INDEX IF NOT EXISTS idx_events_anomaly_score ON events(anomaly_score DESC);

-- ============================================================
-- ENTITIES
-- Known entities with trust levels and feature embeddings
-- ============================================================
CREATE TABLE IF NOT EXISTS entities (
    entity_id           TEXT PRIMARY KEY,
    type                TEXT NOT NULL,  -- vehicle, person, face
    label               TEXT,
    trust_level         TEXT NOT NULL DEFAULT 'unknown',
    role                TEXT,  -- resident, neighbor, delivery, service, passerby, etc.
    first_seen          TIMESTAMPTZ,
    last_seen           TIMESTAMPTZ,
    sightings_count     INT DEFAULT 0,
    -- Vehicle fields
    plate_text          TEXT,
    plate_state         TEXT,
    vehicle_color       TEXT,
    vehicle_make_model  TEXT,
    vehicle_embedding   vector(2000),
    -- Person/face fields
    face_embedding      vector(512),
    -- Alert tuning
    alert_threshold_adjustment FLOAT DEFAULT 0.0,
    -- All other features stored as JSONB
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_trust_level ON entities(trust_level);
CREATE INDEX IF NOT EXISTS idx_entities_plate_text ON entities(plate_text) WHERE plate_text IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen DESC);
-- pgvector indexes for similarity search
CREATE INDEX IF NOT EXISTS idx_entities_face_embedding ON entities USING ivfflat (face_embedding vector_cosine_ops) WITH (lists = 100) WHERE face_embedding IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entities_vehicle_embedding ON entities USING ivfflat (vehicle_embedding vector_cosine_ops) WITH (lists = 100) WHERE vehicle_embedding IS NOT NULL;
-- pg_trgm index for fuzzy plate matching
CREATE INDEX IF NOT EXISTS idx_entities_plate_trgm ON entities USING gin (plate_text gin_trgm_ops) WHERE plate_text IS NOT NULL;

-- ============================================================
-- ENTITY SIGHTINGS
-- Per-event entity observations
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_sightings (
    sighting_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id         TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    event_id          TEXT REFERENCES events(event_id) ON DELETE CASCADE,
    camera_id         TEXT REFERENCES cameras(camera_id) ON DELETE SET NULL,
    timestamp         TIMESTAMPTZ NOT NULL,
    features_snapshot JSONB DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sightings_entity_id ON entity_sightings(entity_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_sightings_event_id ON entity_sightings(event_id);
CREATE INDEX IF NOT EXISTS idx_sightings_camera_timestamp ON entity_sightings(camera_id, timestamp DESC);

-- ============================================================
-- ENTITY AUDIT LOG
-- Full audit trail of trust/role/label changes
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_audit_log (
    log_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id   TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action      TEXT NOT NULL,  -- created, trust_level_changed, labeled, auto_classified, etc.
    actor       TEXT NOT NULL,  -- user, system, auto_classification
    old_values  JSONB DEFAULT '{}'::jsonb,
    new_values  JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_log_entity_id ON entity_audit_log(entity_id, timestamp DESC);

-- ============================================================
-- PATTERNS
-- Baseline traffic and entity patterns per camera/time
-- ============================================================
CREATE TABLE IF NOT EXISTS patterns (
    pattern_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id     TEXT REFERENCES cameras(camera_id) ON DELETE CASCADE,
    entity_id     TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    entity_type   TEXT,
    pattern_type  TEXT DEFAULT 'entity_visit',  -- entity_visit, baseline_traffic
    time_pattern  JSONB DEFAULT '{}'::jsonb,  -- {hour_of_day, day_of_week}
    frequency     FLOAT DEFAULT 1.0,
    last_seen     TIMESTAMPTZ,
    confidence    FLOAT DEFAULT 0.1,
    user_approved BOOLEAN DEFAULT FALSE,
    metadata      JSONB DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patterns_camera_id ON patterns(camera_id);
CREATE INDEX IF NOT EXISTS idx_patterns_entity_id ON patterns(entity_id) WHERE entity_id IS NOT NULL;

-- ============================================================
-- ALERTS
-- Alert history with user feedback
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    alert_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id           TEXT REFERENCES events(event_id) ON DELETE SET NULL,
    entity_id          TEXT REFERENCES entities(entity_id) ON DELETE SET NULL,
    camera_id          TEXT REFERENCES cameras(camera_id) ON DELETE SET NULL,
    timestamp          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    priority           TEXT NOT NULL,  -- critical, high, medium, low
    title              TEXT NOT NULL,
    body               TEXT,
    delivered          BOOLEAN DEFAULT FALSE,
    user_response      TEXT,  -- acknowledged, dismissed, false_positive, acted_upon
    response_timestamp TIMESTAMPTZ,
    metadata           JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_entity_id ON alerts(entity_id) WHERE entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_alerts_camera_id ON alerts(camera_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_priority ON alerts(priority, timestamp DESC);

-- ============================================================
-- ALERT PREFERENCES
-- Per-camera alert configuration
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_preferences (
    camera_id            TEXT PRIMARY KEY,
    sensitivity          TEXT DEFAULT 'balanced',  -- paranoid, balanced, relaxed
    entity_filters       TEXT[],  -- NULL = all types
    quiet_hours_start    INT,  -- hour 0-23
    quiet_hours_end      INT,
    min_anomaly_score    FLOAT DEFAULT 0.5,
    metadata             JSONB DEFAULT '{}'::jsonb,
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);

-- Global default preferences
INSERT INTO alert_preferences (camera_id, sensitivity, min_anomaly_score)
VALUES ('global', 'balanced', 0.5)
ON CONFLICT (camera_id) DO NOTHING;

-- ============================================================
-- ALERT SUPPRESSIONS
-- Snoozed entities/cameras
-- ============================================================
CREATE TABLE IF NOT EXISTS alert_suppressions (
    suppression_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id       TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    camera_id       TEXT REFERENCES cameras(camera_id) ON DELETE CASCADE,
    suppressed_until TIMESTAMPTZ NOT NULL,
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT suppression_target CHECK (entity_id IS NOT NULL OR camera_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_suppressions_entity ON alert_suppressions(entity_id) WHERE entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_suppressions_camera ON alert_suppressions(camera_id) WHERE camera_id IS NOT NULL;

-- ============================================================
-- THREAT ASSESSMENTS
-- Detailed threat analysis records (Phase 3)
-- ============================================================
CREATE TABLE IF NOT EXISTS threat_assessments (
    assessment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id        TEXT REFERENCES events(event_id) ON DELETE SET NULL,
    entity_id       TEXT REFERENCES entities(entity_id) ON DELETE SET NULL,
    camera_id       TEXT REFERENCES cameras(camera_id) ON DELETE SET NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    threat_score    FLOAT NOT NULL,
    threat_level    TEXT NOT NULL,  -- none, low, moderate, high, critical
    dimensions      JSONB DEFAULT '{}'::jsonb,
    recommendations JSONB DEFAULT '[]'::jsonb,
    summary         TEXT
);

CREATE INDEX IF NOT EXISTS idx_threat_assessments_timestamp ON threat_assessments(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_threat_assessments_entity ON threat_assessments(entity_id) WHERE entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_threat_assessments_level ON threat_assessments(threat_level, timestamp DESC);

-- ============================================================
-- HOSTILE EVENTS
-- Hostile behavior records (Phase 3)
-- ============================================================
CREATE TABLE IF NOT EXISTS hostile_events (
    hostile_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         TEXT REFERENCES events(event_id) ON DELETE SET NULL,
    entity_id        TEXT REFERENCES entities(entity_id) ON DELETE SET NULL,
    camera_id        TEXT REFERENCES cameras(camera_id) ON DELETE SET NULL,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggers         JSONB DEFAULT '[]'::jsonb,
    severity         FLOAT NOT NULL,
    actions_taken    JSONB DEFAULT '[]'::jsonb,
    user_confirmed   BOOLEAN,
    false_positive   BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_hostile_events_timestamp ON hostile_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_hostile_events_entity ON hostile_events(entity_id) WHERE entity_id IS NOT NULL;

-- ============================================================
-- COORDINATION EVENTS
-- Coordinated activity records (Phase 3)
-- ============================================================
CREATE TABLE IF NOT EXISTS coordination_events (
    coordination_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_event_id TEXT REFERENCES events(event_id) ON DELETE SET NULL,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    coordination_score FLOAT NOT NULL,
    patterns         JSONB DEFAULT '[]'::jsonb,
    events_involved  TEXT[],
    entities_involved TEXT[],
    alert_generated  BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_coordination_events_timestamp ON coordination_events(timestamp DESC);

-- ============================================================
-- ENTITY TRACKS
-- Cross-camera movement paths (Phase 4)
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_tracks (
    track_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id              TEXT REFERENCES entities(entity_id) ON DELETE CASCADE,
    start_time             TIMESTAMPTZ NOT NULL,
    end_time               TIMESTAMPTZ NOT NULL,
    cameras_visited        TEXT[],
    path_data              JSONB DEFAULT '{}'::jsonb,
    tracking_quality       TEXT,  -- good, moderate, poor
    gaps_count             INT DEFAULT 0,
    total_duration_seconds FLOAT,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entity_tracks_entity_id ON entity_tracks(entity_id, start_time DESC);

-- ============================================================
-- SECURITY BRIEFINGS
-- Daily briefing history (Phase 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS security_briefings (
    briefing_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    assessment    TEXT NOT NULL,  -- ALL CLEAR, MONITOR, ELEVATED ACTIVITY, NEEDS ATTENTION
    briefing_data JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_security_briefings_timestamp ON security_briefings(timestamp DESC);

-- ============================================================
-- SECURITY REPORTS
-- Weekly/monthly report history (Phase 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS security_reports (
    report_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start TIMESTAMPTZ NOT NULL,
    period_end   TIMESTAMPTZ NOT NULL,
    report_type  TEXT NOT NULL,  -- weekly, monthly, quarterly, custom
    report_data  JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_security_reports_timestamp ON security_reports(timestamp DESC);

-- ============================================================
-- FP ANALYSIS
-- False positive root cause analysis (Phase 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS fp_analysis (
    fp_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id            UUID REFERENCES alerts(alert_id) ON DELETE SET NULL,
    event_id            TEXT REFERENCES events(event_id) ON DELETE SET NULL,
    entity_id           TEXT REFERENCES entities(entity_id) ON DELETE SET NULL,
    camera_id           TEXT REFERENCES cameras(camera_id) ON DELETE SET NULL,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    causes              JSONB DEFAULT '[]'::jsonb,
    corrections_applied JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_fp_analysis_timestamp ON fp_analysis(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_fp_analysis_camera ON fp_analysis(camera_id, timestamp DESC);

-- ============================================================
-- OPTIMIZATION RUNS
-- Threshold optimization history (Phase 5)
-- ============================================================
CREATE TABLE IF NOT EXISTS optimization_runs (
    run_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alerts_analyzed  INT NOT NULL,
    metrics_summary  JSONB DEFAULT '{}'::jsonb,
    recommendations  JSONB DEFAULT '[]'::jsonb,
    applied_changes  JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_optimization_runs_timestamp ON optimization_runs(timestamp DESC);

-- ============================================================
-- CAMERA TOPOLOGY
-- Adjacency and transition times between cameras
-- ============================================================
CREATE TABLE IF NOT EXISTS camera_topology (
    topology_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_a             TEXT REFERENCES cameras(camera_id) ON DELETE CASCADE,
    camera_b             TEXT REFERENCES cameras(camera_id) ON DELETE CASCADE,
    distance_meters      FLOAT,
    typical_walk_seconds FLOAT,
    typical_drive_seconds FLOAT,
    notes                TEXT,
    UNIQUE (camera_a, camera_b)
);

-- sentinel_health: single-row table written by Sentinel on startup and periodically.
-- Allows the UI (via protect-query Lambda) to see the agent-side DB / poller status
-- without requiring a direct network path from the UI to the Sentinel agent.
CREATE TABLE IF NOT EXISTS sentinel_health (
    id                   INT PRIMARY KEY DEFAULT 1,  -- always 1; enforces single row
    status               TEXT NOT NULL DEFAULT 'unknown',
    protect_db           TEXT NOT NULL DEFAULT 'unchecked',
    protect_poller       TEXT NOT NULL DEFAULT 'stopped',
    protect_processor    TEXT NOT NULL DEFAULT 'stopped',
    protect_configured   BOOLEAN NOT NULL DEFAULT FALSE,
    uptime_seconds       INT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);
