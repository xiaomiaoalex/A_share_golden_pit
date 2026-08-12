CREATE TABLE IF NOT EXISTS screening_run_control_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    target_status TEXT NOT NULL,
    worker_process_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES screening_runs(run_id),
    CHECK(action IN ('PAUSE','RESUME','STOP'))
);

CREATE INDEX IF NOT EXISTS idx_screening_run_control_events_run
ON screening_run_control_events(run_id, created_at);
