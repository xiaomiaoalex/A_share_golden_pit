CREATE TABLE IF NOT EXISTS strategy_signals (
    signal_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, strategy_id TEXT NOT NULL,
    release_id TEXT NOT NULL, security_id TEXT NOT NULL, symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL, direction TEXT NOT NULL, score REAL NOT NULL,
    rank_value INTEGER NOT NULL, confidence REAL NOT NULL, valid_until TEXT NOT NULL,
    attribution_json TEXT NOT NULL, data_snapshot_id TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(run_id, strategy_id, security_id)
);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_aggregate
ON strategy_signals(as_of_date, strategy_id, rank_value);

CREATE TABLE IF NOT EXISTS research_datasets (
    dataset_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, release_id TEXT NOT NULL,
    as_of_date TEXT NOT NULL, content_hash TEXT NOT NULL, egress_class TEXT NOT NULL,
    manifest_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_templates (
    template_version_id TEXT PRIMARY KEY, template_id TEXT NOT NULL, version INTEGER NOT NULL,
    prompt TEXT NOT NULL, output_schema_json TEXT NOT NULL, model_policy_json TEXT NOT NULL,
    status TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(template_id, version)
);
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, template_version_id TEXT NOT NULL,
    subject TEXT NOT NULL, provider_id TEXT, model_id TEXT, status TEXT NOT NULL,
    usage_json TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES research_datasets(dataset_id),
    FOREIGN KEY(template_version_id) REFERENCES research_templates(template_version_id)
);
CREATE TABLE IF NOT EXISTS research_report_versions (
    report_version_id TEXT PRIMARY KEY, report_id TEXT NOT NULL, run_id TEXT NOT NULL,
    version INTEGER NOT NULL, status TEXT NOT NULL, report_json TEXT NOT NULL,
    actor TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES research_runs(run_id), UNIQUE(report_id, version)
);
CREATE INDEX IF NOT EXISTS idx_research_reports_latest
ON research_report_versions(report_id, version DESC);
