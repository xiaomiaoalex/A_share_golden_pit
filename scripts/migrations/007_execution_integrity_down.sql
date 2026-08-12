DROP INDEX IF EXISTS idx_tier1_current_decision_id;
DROP INDEX IF EXISTS idx_tier1_decision_history_run_symbol;
DROP TABLE IF EXISTS tier1_decision_history;
-- SQLite-safe rollback retains additive columns on existing tables.
