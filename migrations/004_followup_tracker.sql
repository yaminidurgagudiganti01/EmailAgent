-- Migration 004: followup_tracker table
-- Run in Supabase → SQL Editor after 003.

CREATE TABLE IF NOT EXISTS followup_tracker (
    thread_id           TEXT PRIMARY KEY,
    original_message_id TEXT NOT NULL,
    drafted_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              TEXT NOT NULL DEFAULT 'drafted',   -- drafted | sent | dismissed
    followup_message_id TEXT
);

ALTER TABLE followup_tracker ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role full access on followup_tracker"
ON followup_tracker FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE INDEX IF NOT EXISTS followup_tracker_status_idx ON followup_tracker (status);
