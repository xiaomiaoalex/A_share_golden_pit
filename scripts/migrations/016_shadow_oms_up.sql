CREATE TABLE IF NOT EXISTS shadow_orders (
    order_version_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, version INTEGER NOT NULL,
    portfolio_artifact_id TEXT NOT NULL, security_id TEXT NOT NULL, side TEXT NOT NULL,
    quantity INTEGER NOT NULL, status TEXT NOT NULL, actor TEXT NOT NULL,
    note TEXT, created_at TEXT NOT NULL, UNIQUE(order_id, version),
    CHECK(status IN ('CREATED','APPROVED','SUBMITTED','FILLED','REJECTED','CANCELLED'))
);
CREATE TABLE IF NOT EXISTS trading_controls (
    control_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, reason TEXT NOT NULL,
    actor TEXT NOT NULL, created_at TEXT NOT NULL
);
