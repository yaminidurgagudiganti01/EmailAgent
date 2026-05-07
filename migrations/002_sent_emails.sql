-- Email Agent: sent emails tracking
-- Run in Supabase → SQL Editor after 001_initial_schema.sql

CREATE TABLE IF NOT EXISTS sent_emails (
    message_id TEXT PRIMARY KEY,
    email_id   TEXT,
    sent_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    subject    TEXT,
    to_addr    TEXT
);

ALTER TABLE sent_emails ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_full_access" ON sent_emails
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_sent_emails_at
    ON sent_emails (sent_at DESC);
