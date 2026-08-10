CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screening_runs (
    run_id TEXT PRIMARY KEY,
    as_of_date TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    universe_size INTEGER,
    price_date_min TEXT,
    price_date_max TEXT,
    error_summary_json TEXT
);

CREATE TABLE IF NOT EXISTS source_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT,
    field_group TEXT NOT NULL,
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_json TEXT NOT NULL,
    fetch_status TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    available_at TEXT,
    row_count INTEGER,
    schema_hash TEXT,
    payload_hash TEXT,
    error_type TEXT,
    error_message TEXT,
    quality_warnings_json TEXT,
    raw_payload_json TEXT,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id)
);

CREATE TABLE IF NOT EXISTS tier1_raw_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    report_period TEXT,
    period_type TEXT NOT NULL,
    raw_value REAL,
    unit TEXT,
    announcement_date TEXT,
    available_at TEXT,
    source_observation_id INTEGER,
    revision_at TEXT,
    raw_json TEXT,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (source_observation_id) REFERENCES source_observations(id),
    UNIQUE (run_id, symbol, metric_name, report_period, source_observation_id)
);

CREATE TABLE IF NOT EXISTS tier1_quarterly_series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quarter TEXT NOT NULL,
    revenue_single REAL,
    parent_np_single REAL,
    prior_year_revenue_single REAL,
    prior_year_parent_np_single REAL,
    revenue_yoy REAL,
    parent_np_yoy REAL,
    revenue_comparable INTEGER NOT NULL,
    parent_np_comparable INTEGER NOT NULL,
    formula TEXT NOT NULL,
    missing_fields_json TEXT,
    source_observation_ids_json TEXT,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    UNIQUE (run_id, symbol, quarter)
);

CREATE TABLE IF NOT EXISTS dividend_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ex_date TEXT NOT NULL,
    report_period TEXT,
    announcement_date TEXT,
    raw_cash_per_share_pre_tax REAL,
    adjusted_cash_per_share_pre_tax REAL,
    adjustment_factor REAL,
    provider_adjusted INTEGER NOT NULL,
    status TEXT,
    source TEXT NOT NULL,
    source_observation_id INTEGER,
    raw_json TEXT,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (source_observation_id) REFERENCES source_observations(id)
);

CREATE TABLE IF NOT EXISTS risk_warning_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    is_risk_warning INTEGER,
    security_name TEXT,
    effective_date TEXT,
    source TEXT NOT NULL,
    source_observation_id INTEGER,
    reason TEXT,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (source_observation_id) REFERENCES source_observations(id),
    UNIQUE (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS tier1_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    price_date TEXT,
    business_status TEXT NOT NULL,
    data_status TEXT NOT NULL,
    screen_status TEXT NOT NULL,
    selected_pe_ttm REAL,
    supplier_pe_ttm REAL,
    self_pe_ttm REAL,
    pe_selection_method TEXT,
    dividend_yield_ttm REAL,
    dividend_ttm_raw_per_share REAL,
    dividend_ttm_adjusted_per_share REAL,
    risk_warning INTEGER,
    trend_quarters_json TEXT NOT NULL,
    revenue_yoy_sequence_json TEXT NOT NULL,
    parent_np_yoy_sequence_json TEXT NOT NULL,
    failed_conditions_json TEXT NOT NULL,
    pending_fields_json TEXT NOT NULL,
    error_fields_json TEXT NOT NULL,
    skipped_fields_json TEXT NOT NULL,
    not_comparable_reasons_json TEXT NOT NULL,
    quality_warnings_json TEXT NOT NULL,
    secondary_queues_json TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    UNIQUE (run_id, symbol)
);

CREATE TABLE IF NOT EXISTS source_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    field_name TEXT NOT NULL,
    source_observation_id INTEGER,
    source_period TEXT,
    announcement_date TEXT,
    available_at TEXT,
    fetched_at TEXT NOT NULL,
    raw_value TEXT,
    calculated_value TEXT,
    calculation_note TEXT,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (source_observation_id) REFERENCES source_observations(id)
);

CREATE INDEX IF NOT EXISTS idx_tier1_runs_asof
    ON screening_runs(as_of_date, calculation_version);
CREATE INDEX IF NOT EXISTS idx_source_observation_run_symbol
    ON source_observations(run_id, symbol, field_group);
CREATE INDEX IF NOT EXISTS idx_tier1_raw_run_symbol_period
    ON tier1_raw_metrics(run_id, symbol, report_period);
CREATE INDEX IF NOT EXISTS idx_tier1_quarter_run_symbol
    ON tier1_quarterly_series(run_id, symbol, quarter);
CREATE INDEX IF NOT EXISTS idx_tier1_decision_run_status
    ON tier1_decisions(run_id, screen_status, data_status);
CREATE INDEX IF NOT EXISTS idx_lineage_run_symbol_field
    ON source_lineage(run_id, symbol, field_name);
