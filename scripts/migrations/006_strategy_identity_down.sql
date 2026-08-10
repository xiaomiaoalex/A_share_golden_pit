-- SQLite-safe rollback: remove the lookup index but retain strategy_id and data.
-- A destructive table rebuild is intentionally avoided.
DROP INDEX IF EXISTS idx_screening_runs_strategy_started;
