ALTER TABLE screening_runs ADD COLUMN release_manifest_json TEXT;
ALTER TABLE tier1_decisions ADD COLUMN decision_id TEXT;
ALTER TABLE tier1_decisions ADD COLUMN decision_version INTEGER;
ALTER TABLE tier1_item_attempts ADD COLUMN decision_id TEXT;

CREATE TABLE IF NOT EXISTS tier1_decision_history (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    attempt_id TEXT,
    decision_version INTEGER NOT NULL,
    calculation_version TEXT NOT NULL,
    decision_hash TEXT NOT NULL,
    decision_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (attempt_id) REFERENCES tier1_item_attempts(attempt_id),
    UNIQUE (run_id, symbol, decision_version),
    UNIQUE (attempt_id)
);

CREATE INDEX IF NOT EXISTS idx_tier1_decision_history_run_symbol
ON tier1_decision_history(run_id, symbol, decision_version DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tier1_current_decision_id
ON tier1_decisions(decision_id) WHERE decision_id IS NOT NULL;
