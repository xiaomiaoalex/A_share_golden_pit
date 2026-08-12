CREATE TABLE IF NOT EXISTS securities (
    security_id TEXT PRIMARY KEY, issuer_name TEXT NOT NULL,
    listed_at TEXT, delisted_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS security_code_history (
    security_id TEXT NOT NULL, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
    valid_from TEXT NOT NULL, valid_to TEXT, name TEXT NOT NULL,
    PRIMARY KEY(security_id, valid_from),
    FOREIGN KEY(security_id) REFERENCES securities(security_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_security_code_point_in_time
ON security_code_history(symbol, exchange, valid_from);
CREATE TABLE IF NOT EXISTS security_status_history (
    status_id TEXT PRIMARY KEY, security_id TEXT NOT NULL, status_type TEXT NOT NULL,
    status_value TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
    source_record_id TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(security_id) REFERENCES securities(security_id)
);
CREATE TABLE IF NOT EXISTS trading_calendar (
    exchange TEXT NOT NULL, trade_date TEXT NOT NULL, is_open INTEGER NOT NULL,
    session_json TEXT NOT NULL, source_record_id TEXT NOT NULL,
    PRIMARY KEY(exchange, trade_date)
);
CREATE TABLE IF NOT EXISTS corporate_actions (
    action_id TEXT PRIMARY KEY, security_id TEXT NOT NULL, action_type TEXT NOT NULL,
    announcement_date TEXT NOT NULL, effective_date TEXT NOT NULL,
    payload_json TEXT NOT NULL, source_record_id TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(security_id) REFERENCES securities(security_id)
);
CREATE TABLE IF NOT EXISTS financial_report_versions (
    report_version_id TEXT PRIMARY KEY, security_id TEXT NOT NULL,
    report_period TEXT NOT NULL, announcement_date TEXT NOT NULL,
    revision INTEGER NOT NULL, payload_json TEXT NOT NULL, content_hash TEXT NOT NULL,
    source_record_id TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(security_id) REFERENCES securities(security_id),
    UNIQUE(security_id, report_period, revision)
);
CREATE INDEX IF NOT EXISTS idx_financial_report_asof
ON financial_report_versions(security_id, announcement_date, report_period, revision);
CREATE TABLE IF NOT EXISTS data_snapshots (
    snapshot_id TEXT PRIMARY KEY, dataset_type TEXT NOT NULL, as_of_date TEXT NOT NULL,
    parquet_path TEXT NOT NULL, content_hash TEXT NOT NULL, row_count INTEGER NOT NULL,
    schema_json TEXT NOT NULL, lineage_json TEXT NOT NULL, quality_json TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(dataset_type, as_of_date, content_hash)
);
CREATE TABLE IF NOT EXISTS field_egress_policies (
    field_path TEXT PRIMARY KEY, egress_class TEXT NOT NULL,
    mask_rule TEXT, updated_at TEXT NOT NULL
);
