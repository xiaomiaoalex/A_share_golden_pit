CREATE TABLE IF NOT EXISTS tier3_risk_inputs (
    input_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    tier2_review_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    industry_model TEXT NOT NULL,
    industry_classification_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    input_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (tier2_review_id) REFERENCES human_reviews(review_id),
    UNIQUE (tier2_review_id, content_hash)
);

CREATE TABLE IF NOT EXISTS tier3_risk_checks (
    check_result_id TEXT PRIMARY KEY,
    input_id TEXT NOT NULL,
    check_id TEXT NOT NULL,
    category TEXT NOT NULL,
    rule_effect TEXT NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    facts_json TEXT NOT NULL,
    inferences_json TEXT NOT NULL,
    counter_evidence_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    reasoning_summary TEXT NOT NULL,
    FOREIGN KEY (input_id) REFERENCES tier3_risk_inputs(input_id),
    UNIQUE (input_id, check_id)
);

CREATE TABLE IF NOT EXISTS tier3_risk_assessments (
    risk_assessment_id TEXT PRIMARY KEY,
    input_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    tier2_review_id TEXT NOT NULL,
    industry_model TEXT NOT NULL,
    industry_model_class TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    assessment_version TEXT NOT NULL,
    system_status TEXT NOT NULL,
    data_status TEXT NOT NULL,
    hard_vetoes_json TEXT NOT NULL,
    risk_warnings_json TEXT NOT NULL,
    value_trap_signals_json TEXT NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    counter_evidence_json TEXT NOT NULL,
    unknown_checks_json TEXT NOT NULL,
    falsification_conditions_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (input_id) REFERENCES tier3_risk_inputs(input_id),
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (tier2_review_id) REFERENCES human_reviews(review_id)
);

CREATE TABLE IF NOT EXISTS tier3_human_reviews (
    review_id TEXT PRIMARY KEY,
    risk_assessment_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    rationale TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    supersedes_review_id TEXT,
    FOREIGN KEY (risk_assessment_id) REFERENCES tier3_risk_assessments(risk_assessment_id),
    FOREIGN KEY (run_id) REFERENCES screening_runs(run_id),
    FOREIGN KEY (supersedes_review_id) REFERENCES tier3_human_reviews(review_id),
    CHECK (decision IN ('PASS', 'REVIEW', 'REJECT'))
);

CREATE INDEX IF NOT EXISTS idx_tier3_inputs_run_symbol
    ON tier3_risk_inputs(run_id, symbol, imported_at);
CREATE INDEX IF NOT EXISTS idx_tier3_assessments_run_status
    ON tier3_risk_assessments(run_id, system_status, symbol);
CREATE INDEX IF NOT EXISTS idx_tier3_reviews_run_symbol
    ON tier3_human_reviews(run_id, symbol, reviewed_at);
