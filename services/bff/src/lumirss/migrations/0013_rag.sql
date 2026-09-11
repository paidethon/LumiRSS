-- 0013: RAG projection (phase2 G7). rag_chunks is derived/rebuildable
-- from the RSS and library projections; the vec0 virtual table is
-- created at runtime by the RAG service when the sqlite-vec extension
-- is loadable (its absence degrades semantic search to lexical only).
CREATE TABLE rag_chunks (
  chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT NOT NULL,
  ord INTEGER NOT NULL,
  model_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  embedding BLOB,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ux_rag_ref_ord ON rag_chunks(ref, ord, model_id);
CREATE INDEX ix_rag_model ON rag_chunks(model_id);
