ALTER TABLE screening_run_leases ADD COLUMN fence_token INTEGER NOT NULL DEFAULT 1;
ALTER TABLE screening_run_leases ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS screening_run_lease_sequences (
    run_id TEXT PRIMARY KEY,
    last_fence_token INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    CHECK (last_fence_token > 0)
);

INSERT INTO screening_run_lease_sequences(run_id, last_fence_token)
SELECT run_id, MAX(fence_token)
FROM screening_run_leases
GROUP BY run_id
ON CONFLICT(run_id) DO UPDATE SET
    last_fence_token=MAX(last_fence_token, excluded.last_fence_token);
