CREATE TABLE IF NOT EXISTS platform_artifacts (
    artifact_version_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
    strategy_id TEXT, release_id TEXT, data_snapshot_id TEXT,
    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(artifact_id, version)
);
CREATE INDEX IF NOT EXISTS idx_platform_artifacts_type_latest
ON platform_artifacts(artifact_type, artifact_id, version DESC);
