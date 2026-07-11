-- 0006 — semantic search / dedup (pgvector) + learning hints

-- Chunked source text for semantic search & carry-over matching.
create table source_chunks (
  id         uuid primary key default gen_random_uuid(),
  source_id  uuid not null references sources(id) on delete cascade,
  chunk      text not null,
  embedding  vector(1024)
);
create index source_chunks_source_idx on source_chunks (source_id);
-- IVFFlat index for cosine similarity; tune lists after seed volume is known.
create index source_chunks_embedding_idx on source_chunks
  using ivfflat (embedding vector_cosine_ops) with (lists = 100);

create table item_embeddings (
  item_id    uuid primary key references items(id) on delete cascade,
  embedding  vector(1024)
);
create index item_embeddings_embedding_idx on item_embeddings
  using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Learning output: hints derived from what the CEO edits/deletes over time.
create table extraction_hints (
  id            uuid primary key default gen_random_uuid(),
  scope         text,                                  -- e.g. 'section:top'
  hint          text not null,
  created_from  text,                                  -- e.g. 'delete-pattern' | 'edit-pattern'
  created_at    timestamptz not null default now()
);
