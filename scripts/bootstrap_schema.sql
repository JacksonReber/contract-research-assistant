-- Schema for chat history persistence.
-- Run with: PGPASSWORD=$(databricks postgres generate-database-credential --json '{"endpoint":"<ENDPOINT_NAME>"}' --output json | jq -r .token) \
--          psql -h <PGHOST> -U <PGUSER> -d databricks_postgres -f scripts/bootstrap_schema.sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS threads (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_email  TEXT NOT NULL,
  title       TEXT NOT NULL DEFAULT 'New chat',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS threads_user_email_idx
  ON threads(user_email, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id   UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content     TEXT NOT NULL,
  citations   JSONB,
  trace_id    TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_thread_idx
  ON messages(thread_id, created_at);

-- After deploy, grant access to the app SP role (replace <sp-client-id>):
-- GRANT ALL ON threads, messages TO "<sp-client-id>";
