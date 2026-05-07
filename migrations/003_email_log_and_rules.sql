-- Migration 003: email_log and exclude_rules tables
-- Run this in the Supabase SQL Editor after 001 and 002.

-- ── email_log ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_log (
    id         BIGSERIAL PRIMARY KEY,
    email_id   TEXT NOT NULL,
    from_addr  TEXT,
    subject    TEXT,
    category   TEXT,
    priority   TEXT,
    draft_id   TEXT,
    sent       BOOLEAN DEFAULT FALSE,
    logged_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE email_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role full access on email_log"
ON email_log FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE INDEX IF NOT EXISTS email_log_logged_at_idx ON email_log (logged_at DESC);

-- ── exclude_rules ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS exclude_rules (
    id         BIGSERIAL PRIMARY KEY,
    rule_type  TEXT NOT NULL,        -- 'sender' | 'domain' | 'category'
    value      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(rule_type, value)
);

ALTER TABLE exclude_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role full access on exclude_rules"
ON exclude_rules FOR ALL
TO service_role
USING (true)
WITH CHECK (true);
