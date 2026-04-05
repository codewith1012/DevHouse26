CREATE TABLE IF NOT EXISTS developers (
  developer_id        VARCHAR(100) PRIMARY KEY,
  name                TEXT NOT NULL,
  email               TEXT UNIQUE,
  age                 INTEGER,
  role                VARCHAR(50),
  experience_years    NUMERIC(4,1) NOT NULL DEFAULT 0,
  seniority_level     VARCHAR(20) NOT NULL DEFAULT 'mid',
  tech_stack          JSONB NOT NULL DEFAULT '[]'::JSONB,
  summary             TEXT,
  current_capacity    INTEGER NOT NULL DEFAULT 3,
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_developers_active
  ON developers (active);

CREATE INDEX IF NOT EXISTS idx_developers_role
  ON developers (role);

CREATE OR REPLACE FUNCTION update_developers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_developers_updated_at ON developers;
CREATE TRIGGER trg_developers_updated_at
  BEFORE UPDATE ON developers
  FOR EACH ROW EXECUTE FUNCTION update_developers_updated_at();

ALTER TABLE developers ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE developers TO service_role;
GRANT SELECT ON TABLE developers TO anon;
GRANT SELECT ON TABLE developers TO authenticated;

CREATE POLICY "service_role_full_access_developers"
ON developers
AS PERMISSIVE
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "public_read_developers"
ON developers
AS PERMISSIVE
FOR SELECT
TO anon, authenticated
USING (true);
