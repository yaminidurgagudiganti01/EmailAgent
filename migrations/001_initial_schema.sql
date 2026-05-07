-- Email Agent: initial schema
-- Run this once in Supabase → SQL Editor before connecting the agent.

CREATE TABLE IF NOT EXISTS processed_emails (
    email_id     TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    draft_id     TEXT
);

-- Enable Row Level Security (required by Supabase security advisor)
ALTER TABLE processed_emails ENABLE ROW LEVEL SECURITY;

-- The agent connects with the service_role key which bypasses RLS by default,
-- so this policy exists only to satisfy the security advisor while keeping
-- the table locked to unprivileged anon/authenticated roles.
CREATE POLICY "service_role_full_access" ON processed_emails
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Index speeds up the idempotency check on every email processed
CREATE INDEX IF NOT EXISTS idx_processed_emails_at
    ON processed_emails (processed_at DESC);
