CREATE TABLE IF NOT EXISTS strategy_change_proposals (
    proposal_id TEXT PRIMARY KEY, strategy_id TEXT NOT NULL, base_release_id TEXT NOT NULL,
    status TEXT NOT NULL, change_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    CHECK(status IN ('DRAFT','UNDER_REVIEW','APPROVED','REJECTED'))
);
CREATE TABLE IF NOT EXISTS provider_budgets (
    provider_id TEXT NOT NULL, period TEXT NOT NULL, budget REAL NOT NULL,
    spent REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
    PRIMARY KEY(provider_id, period), CHECK(budget >= 0), CHECK(spent >= 0)
);
