-- ================================================================
-- Requirement Risk Predictive Engine storage
-- ================================================================

CREATE TABLE IF NOT EXISTS requirement_risk_scores (
  requirement_id   VARCHAR(50) PRIMARY KEY,
  title            TEXT,
  status           VARCHAR(50),
  due_date         DATE,
  days_remaining   NUMERIC(10,2),
  risk_score       NUMERIC(6,4) NOT NULL DEFAULT 0,
  risk_level       VARCHAR(16) NOT NULL,
  breakdown        JSONB NOT NULL DEFAULT '{}'::JSONB,
  reasons          JSONB NOT NULL DEFAULT '[]'::JSONB,
  recommendations  JSONB NOT NULL DEFAULT '[]'::JSONB,
  inputs           JSONB NOT NULL DEFAULT '{}'::JSONB,
  engine_version   VARCHAR(32) NOT NULL DEFAULT 'v1',
  calculated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE requirement_risk_scores
  ADD COLUMN IF NOT EXISTS days_remaining NUMERIC(10,2);

CREATE INDEX IF NOT EXISTS idx_requirement_risk_scores_level
  ON requirement_risk_scores (risk_level);

CREATE INDEX IF NOT EXISTS idx_requirement_risk_scores_score
  ON requirement_risk_scores (risk_score DESC);

CREATE INDEX IF NOT EXISTS idx_requirement_risk_scores_due_date
  ON requirement_risk_scores (due_date);

CREATE OR REPLACE FUNCTION update_requirement_risk_scores_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_requirement_risk_scores_updated_at ON requirement_risk_scores;
CREATE TRIGGER trg_requirement_risk_scores_updated_at
  BEFORE UPDATE ON requirement_risk_scores
  FOR EACH ROW EXECUTE FUNCTION update_requirement_risk_scores_updated_at();
