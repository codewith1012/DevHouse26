CREATE TABLE IF NOT EXISTS requirement_developer_recommendations (
  id                  BIGSERIAL PRIMARY KEY,
  requirement_id      VARCHAR(50) NOT NULL,
  developer_id        VARCHAR(100) NOT NULL,
  developer_name      TEXT,
  developer_email     TEXT,
  role                VARCHAR(50),
  experience_years    NUMERIC(4,1),
  tech_stack          JSONB NOT NULL DEFAULT '[]'::JSONB,
  score               NUMERIC(6,4) NOT NULL DEFAULT 0,
  rank                INTEGER NOT NULL DEFAULT 1,
  skill_match         NUMERIC(6,4) NOT NULL DEFAULT 0,
  familiarity_match   NUMERIC(6,4) NOT NULL DEFAULT 0,
  experience_fit      NUMERIC(6,4) NOT NULL DEFAULT 0,
  availability_score  NUMERIC(6,4) NOT NULL DEFAULT 0,
  reasons             JSONB NOT NULL DEFAULT '[]'::JSONB,
  breakdown           JSONB NOT NULL DEFAULT '{}'::JSONB,
  engine_version      VARCHAR(32) NOT NULL DEFAULT 'v1',
  calculated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (requirement_id, developer_id)
);

CREATE INDEX IF NOT EXISTS idx_req_dev_reco_requirement
  ON requirement_developer_recommendations (requirement_id);

CREATE INDEX IF NOT EXISTS idx_req_dev_reco_score
  ON requirement_developer_recommendations (requirement_id, score DESC);

CREATE OR REPLACE FUNCTION update_requirement_developer_recommendations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_requirement_developer_recommendations_updated_at
ON requirement_developer_recommendations;

CREATE TRIGGER trg_requirement_developer_recommendations_updated_at
  BEFORE UPDATE ON requirement_developer_recommendations
  FOR EACH ROW EXECUTE FUNCTION update_requirement_developer_recommendations_updated_at();

ALTER TABLE requirement_developer_recommendations ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE requirement_developer_recommendations TO service_role;
GRANT SELECT ON TABLE requirement_developer_recommendations TO anon;
GRANT SELECT ON TABLE requirement_developer_recommendations TO authenticated;

GRANT USAGE, SELECT ON SEQUENCE requirement_developer_recommendations_id_seq TO service_role;
GRANT USAGE, SELECT ON SEQUENCE requirement_developer_recommendations_id_seq TO anon;
GRANT USAGE, SELECT ON SEQUENCE requirement_developer_recommendations_id_seq TO authenticated;

CREATE POLICY "service_role_full_access_requirement_developer_recommendations"
ON requirement_developer_recommendations
AS PERMISSIVE
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "public_read_requirement_developer_recommendations"
ON requirement_developer_recommendations
AS PERMISSIVE
FOR SELECT
TO anon, authenticated
USING (true);
