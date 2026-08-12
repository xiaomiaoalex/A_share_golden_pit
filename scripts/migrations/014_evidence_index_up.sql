CREATE TABLE IF NOT EXISTS evidence_documents (
    document_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, title TEXT NOT NULL,
    publisher TEXT NOT NULL, published_at TEXT NOT NULL, source_uri TEXT NOT NULL,
    content_hash TEXT NOT NULL, egress_class TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(dataset_id) REFERENCES research_datasets(dataset_id)
);
CREATE TABLE IF NOT EXISTS evidence_chunks (
    chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
    embedding_json TEXT, created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES evidence_documents(document_id),
    FOREIGN KEY(dataset_id) REFERENCES research_datasets(dataset_id),
    UNIQUE(document_id, ordinal)
);
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_chunks_fts USING fts5(
    chunk_id UNINDEXED, dataset_id UNINDEXED, title, content,
    tokenize='unicode61'
);
