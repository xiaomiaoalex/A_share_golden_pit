ALTER TABLE tier1_decisions ADD COLUMN latest_fiscal_year INTEGER;
ALTER TABLE tier1_decisions ADD COLUMN latest_fiscal_year_dividend_yield REAL;
ALTER TABLE tier1_decisions ADD COLUMN latest_fiscal_year_dividend_raw_per_share REAL;
ALTER TABLE tier1_decisions ADD COLUMN latest_fiscal_year_dividend_adjusted_per_share REAL;

CREATE TABLE IF NOT EXISTS tier1_decision_supersessions (
    old_decision_id TEXT PRIMARY KEY,
    new_decision_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    old_run_id TEXT NOT NULL,
    new_run_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    invalidated_at TEXT NOT NULL,
    FOREIGN KEY (old_decision_id) REFERENCES tier1_decision_history(decision_id),
    FOREIGN KEY (new_decision_id) REFERENCES tier1_decision_history(decision_id),
    FOREIGN KEY (old_run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (new_run_id) REFERENCES screening_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_tier1_supersessions_new_decision
ON tier1_decision_supersessions(new_decision_id);

CREATE INDEX IF NOT EXISTS idx_tier1_supersessions_symbol_asof
ON tier1_decision_supersessions(symbol, as_of_date);
