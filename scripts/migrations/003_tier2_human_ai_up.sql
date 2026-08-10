CREATE TABLE IF NOT EXISTS tier2_evidence_packages (
    package_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    package_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    coverage_status TEXT NOT NULL,
    missing_sections_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    json_path TEXT,
    markdown_path TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    UNIQUE (run_id, symbol, content_hash)
);

CREATE TABLE IF NOT EXISTS ai_assessments (
    assessment_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    ai_provider TEXT NOT NULL,
    ai_model TEXT,
    ai_recommendation TEXT NOT NULL,
    system_recommendation TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    assessment_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (package_id) REFERENCES tier2_evidence_packages(package_id),
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    UNIQUE (package_id, content_hash)
);

CREATE TABLE IF NOT EXISTS human_reviews (
    review_id TEXT PRIMARY KEY,
    assessment_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    rationale TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    supersedes_review_id TEXT,
    FOREIGN KEY (assessment_id) REFERENCES ai_assessments(assessment_id),
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (supersedes_review_id) REFERENCES human_reviews(review_id),
    CHECK (decision IN ('PASS', 'REVIEW', 'REJECT'))
);

CREATE INDEX IF NOT EXISTS idx_tier2_packages_run_symbol
    ON tier2_evidence_packages(run_id, symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_assessments_run_symbol
    ON ai_assessments(run_id, symbol, imported_at);
CREATE INDEX IF NOT EXISTS idx_human_reviews_run_symbol
    ON human_reviews(run_id, symbol, reviewed_at);
