CREATE TABLE IF NOT EXISTS governance_releases (
    release_version_id TEXT PRIMARY KEY, release_id TEXT NOT NULL,
    object_type TEXT NOT NULL, object_id TEXT NOT NULL, version INTEGER NOT NULL,
    status TEXT NOT NULL, manifest_json TEXT NOT NULL, actor TEXT NOT NULL,
    note TEXT, created_at TEXT NOT NULL, UNIQUE(release_id, version)
);
CREATE INDEX IF NOT EXISTS idx_governance_release_latest
ON governance_releases(release_id, version DESC);
CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
    object_type TEXT NOT NULL, object_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_bindings (
    actor TEXT NOT NULL, role TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(actor, role)
);
