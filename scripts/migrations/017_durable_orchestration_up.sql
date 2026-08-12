CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_run_id TEXT PRIMARY KEY, workflow_type TEXT NOT NULL,
    priority INTEGER NOT NULL, status TEXT NOT NULL, metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(status IN ('QUEUED','RUNNING','PAUSED','SUCCEEDED','FAILED','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS workflow_nodes (
    node_id TEXT NOT NULL, workflow_run_id TEXT NOT NULL, node_type TEXT NOT NULL,
    dependency_ids_json TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL,
    retry_budget INTEGER NOT NULL, payload_json TEXT NOT NULL, result_json TEXT,
    error_category TEXT, error_message TEXT, updated_at TEXT NOT NULL,
    PRIMARY KEY(workflow_run_id, node_id),
    FOREIGN KEY(workflow_run_id) REFERENCES workflow_runs(workflow_run_id),
    CHECK(status IN ('BLOCKED','READY','RUNNING','SUCCEEDED','FAILED','DEAD_LETTER','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS workflow_dead_letters (
    dead_letter_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, workflow_run_id TEXT NOT NULL,
    payload_json TEXT NOT NULL, error_category TEXT NOT NULL,
    error_message TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(workflow_run_id, node_id)
        REFERENCES workflow_nodes(workflow_run_id, node_id)
);
CREATE TABLE IF NOT EXISTS circuit_breakers (
    resource_id TEXT PRIMARY KEY, status TEXT NOT NULL, failure_count INTEGER NOT NULL,
    threshold_value INTEGER NOT NULL, opened_at TEXT, updated_at TEXT NOT NULL,
    CHECK(status IN ('CLOSED','OPEN','HALF_OPEN'))
);
