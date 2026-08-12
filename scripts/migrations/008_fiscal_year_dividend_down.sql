DROP INDEX IF EXISTS idx_tier1_supersessions_symbol_asof;
DROP INDEX IF EXISTS idx_tier1_supersessions_new_decision;
DROP TABLE IF EXISTS tier1_decision_supersessions;

-- SQLite cannot safely drop the four additive columns on legacy runtimes.
-- Rollback therefore removes the validity relation while preserving data.
