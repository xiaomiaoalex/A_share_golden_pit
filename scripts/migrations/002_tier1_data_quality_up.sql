ALTER TABLE screening_runs ADD COLUMN data_quality_summary_json TEXT;

CREATE TABLE IF NOT EXISTS data_quality_assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT,
    field_group TEXT NOT NULL,
    source_observation_id INTEGER,
    provider TEXT NOT NULL,
    capability TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    severity TEXT NOT NULL,
    blocking INTEGER NOT NULL,
    issues_json TEXT NOT NULL,
    assessed_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (source_observation_id) REFERENCES source_observations(id)
);

CREATE TABLE IF NOT EXISTS source_verification_reports (
    verification_id TEXT PRIMARY KEY,
    run_id TEXT,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    overall_verdict TEXT NOT NULL,
    providers_json TEXT NOT NULL,
    responses_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_quality_run_symbol_group
    ON data_quality_assessments(run_id, symbol, field_group);
CREATE INDEX IF NOT EXISTS idx_quality_run_blocking
    ON data_quality_assessments(run_id, blocking, severity);
CREATE INDEX IF NOT EXISTS idx_verification_symbol_asof
    ON source_verification_reports(symbol, as_of_date, overall_verdict);
