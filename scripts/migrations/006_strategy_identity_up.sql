ALTER TABLE screening_runs
ADD COLUMN strategy_id TEXT NOT NULL DEFAULT 'golden-pit';

CREATE INDEX IF NOT EXISTS idx_screening_runs_strategy_started
ON screening_runs(strategy_id, started_at DESC);
