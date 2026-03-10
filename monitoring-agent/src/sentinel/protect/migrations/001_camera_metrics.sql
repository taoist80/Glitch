-- Migration 001: Expand cameras table with Protect integration API fields
-- Safe to re-run: all statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS

ALTER TABLE cameras ADD COLUMN IF NOT EXISTS mac TEXT;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS model_key TEXT;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS is_mic_enabled BOOLEAN;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS mic_volume INT;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS video_mode TEXT;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS hdr_type TEXT;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS has_hdr BOOLEAN;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS has_mic BOOLEAN;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS has_speaker BOOLEAN;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS has_led_status BOOLEAN;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS has_full_hd_snapshot BOOLEAN;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS video_modes TEXT[];
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS smart_detect_types TEXT[];
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS smart_detect_audio_types TEXT[];
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS smart_detect_object_types TEXT[];
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS smart_detect_audio_config TEXT[];
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS led_settings JSONB DEFAULT '{}'::jsonb;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS osd_settings JSONB DEFAULT '{}'::jsonb;
ALTER TABLE cameras ADD COLUMN IF NOT EXISTS lcd_message JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_cameras_state ON cameras(state);
CREATE INDEX IF NOT EXISTS idx_cameras_mac ON cameras(mac) WHERE mac IS NOT NULL;
