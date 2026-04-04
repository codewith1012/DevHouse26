-- ================================================================
-- DevPulse — req_code_mapping table
-- ================================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS req_code_mapping (
  issue_id        VARCHAR(50)   PRIMARY KEY,
  title           TEXT          NOT NULL,
  description     TEXT,
  status          VARCHAR(50),
  issue_type      VARCHAR(50),
  priority        VARCHAR(20),
  project_key     VARCHAR(50),
  assignee_email  VARCHAR(255),
  reporter_email  VARCHAR(255),
  jira_created_at TIMESTAMPTZ,
  jira_updated_at TIMESTAMPTZ,
  embedding       vector(384) NULL,

  -- List of commit_hashes linked to this requirement
  commits         JSONB         NOT NULL DEFAULT '[]'::JSONB,

  created_at      TIMESTAMPTZ   DEFAULT NOW(),
  updated_at      TIMESTAMPTZ   DEFAULT NOW()
);

ALTER TABLE req_code_mapping
  ADD COLUMN IF NOT EXISTS embedding vector(384);

CREATE INDEX IF NOT EXISTS idx_rcm_status   ON req_code_mapping (status);
CREATE INDEX IF NOT EXISTS idx_rcm_project  ON req_code_mapping (project_key);
CREATE INDEX IF NOT EXISTS idx_rcm_commits_gin ON req_code_mapping USING GIN (commits);
CREATE INDEX IF NOT EXISTS idx_req_embedding
  ON req_code_mapping USING ivfflat (embedding vector_cosine_ops);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_rcm_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_rcm_updated_at ON req_code_mapping;
CREATE TRIGGER trg_rcm_updated_at
  BEFORE UPDATE ON req_code_mapping
  FOR EACH ROW EXECUTE FUNCTION update_rcm_updated_at();

-- Helper: safely append a commit to a requirement (idempotent)
CREATE OR REPLACE FUNCTION append_commit_to_req(
  p_issue_id    TEXT,
  p_commit_hash TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE req_code_mapping
  SET commits = commits || to_jsonb(p_commit_hash)
  WHERE issue_id = p_issue_id
    AND NOT (commits @> to_jsonb(p_commit_hash));
END;
$$;
