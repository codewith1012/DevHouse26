-- ================================================================
-- Requirement Effort Estimation Engine storage
-- ================================================================

CREATE TABLE IF NOT EXISTS requirement_effort_estimates (
  requirement_id            VARCHAR(50) PRIMARY KEY,
  title                     TEXT,
  status                    VARCHAR(50),
  due_date                  DATE,
  initial_estimate_hours    NUMERIC(10,2) NOT NULL DEFAULT 0,
  heuristic_estimate_hours  NUMERIC(10,2) NOT NULL DEFAULT 0,
  llm_estimate_hours        NUMERIC(10,2),
  final_estimate_hours      NUMERIC(10,2) NOT NULL DEFAULT 0,
  remaining_estimate_hours  NUMERIC(10,2) NOT NULL DEFAULT 0,
  completed_effort_hours    NUMERIC(10,2) NOT NULL DEFAULT 0,
  confidence                NUMERIC(6,4) NOT NULL DEFAULT 0,
  estimate_level            VARCHAR(16) NOT NULL DEFAULT 'M',
  drift_hours               NUMERIC(10,2) NOT NULL DEFAULT 0,
  drift_direction           VARCHAR(16) NOT NULL DEFAULT 'stable',
  breakdown                 JSONB NOT NULL DEFAULT '{}'::JSONB,
  rationale                 JSONB NOT NULL DEFAULT '[]'::JSONB,
  task_breakdown            JSONB NOT NULL DEFAULT '[]'::JSONB,
  inputs                    JSONB NOT NULL DEFAULT '{}'::JSONB,
  engine_version            VARCHAR(32) NOT NULL DEFAULT 'v1',
  calculated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_requirement_effort_estimates_final
  ON requirement_effort_estimates (final_estimate_hours DESC);

CREATE INDEX IF NOT EXISTS idx_requirement_effort_estimates_remaining
  ON requirement_effort_estimates (remaining_estimate_hours DESC);

CREATE INDEX IF NOT EXISTS idx_requirement_effort_estimates_level
  ON requirement_effort_estimates (estimate_level);

CREATE INDEX IF NOT EXISTS idx_requirement_effort_estimates_due_date
  ON requirement_effort_estimates (due_date);

CREATE OR REPLACE FUNCTION update_requirement_effort_estimates_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_requirement_effort_estimates_updated_at ON requirement_effort_estimates;
CREATE TRIGGER trg_requirement_effort_estimates_updated_at
  BEFORE UPDATE ON requirement_effort_estimates
  FOR EACH ROW EXECUTE FUNCTION update_requirement_effort_estimates_updated_at();

ALTER TABLE requirement_effort_estimates ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE requirement_effort_estimates TO service_role;
GRANT SELECT ON TABLE requirement_effort_estimates TO anon;
GRANT SELECT ON TABLE requirement_effort_estimates TO authenticated;

CREATE POLICY "service_role_full_access_requirement_effort_estimates"
ON requirement_effort_estimates
AS PERMISSIVE
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

CREATE POLICY "public_read_requirement_effort_estimates"
ON requirement_effort_estimates
AS PERMISSIVE
FOR SELECT
TO anon, authenticated
USING (true);
