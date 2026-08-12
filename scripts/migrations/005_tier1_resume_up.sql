CREATE TABLE IF NOT EXISTS screening_universe_snapshots (
    run_id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    snapshot_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id)
);

CREATE TABLE IF NOT EXISTS screening_run_universe (
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    position INTEGER NOT NULL,
    item_status TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_trigger TEXT,
    last_attempt_started_at TEXT,
    last_attempt_finished_at TEXT,
    last_error_type TEXT,
    last_error_message TEXT,
    PRIMARY KEY (run_id, symbol),
    UNIQUE (run_id, position),
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    CHECK (item_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'RETRYABLE_FAILED')),
    CHECK (attempt_count >= 0)
);

CREATE TABLE IF NOT EXISTS tier1_item_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    trigger_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_type TEXT,
    error_message TEXT,
    decision_status TEXT,
    data_status TEXT,
    FOREIGN KEY (run_id, symbol) REFERENCES screening_run_universe(run_id, symbol),
    UNIQUE (run_id, symbol, attempt_no),
    CHECK (trigger_type IN ('INITIAL', 'RESUME', 'DATA_RETRY')),
    CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS screening_run_leases (
    run_id TEXT PRIMARY KEY,
    worker_token TEXT NOT NULL,
    process_id INTEGER,
    host_name TEXT,
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_universe_status_position
    ON screening_run_universe(run_id, item_status, position);
CREATE INDEX IF NOT EXISTS idx_item_attempts_run_symbol
    ON tier1_item_attempts(run_id, symbol, attempt_no);
CREATE INDEX IF NOT EXISTS idx_run_leases_expiry
    ON screening_run_leases(lease_expires_at);
