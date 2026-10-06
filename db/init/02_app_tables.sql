SET search_path = app, public;

CREATE TABLE schema_docs (
    id            SERIAL PRIMARY KEY,
    db_id         TEXT NOT NULL DEFAULT '',
    table_name    TEXT NOT NULL,
    column_name   TEXT NOT NULL,
    description   TEXT,
    sample_values TEXT,
    embedding     vector(384)
);

CREATE TABLE examples (
    id        SERIAL PRIMARY KEY,
    db_id     TEXT NOT NULL DEFAULT '',
    question  TEXT NOT NULL,
    evidence  TEXT,
    sql       TEXT NOT NULL,
    verified  BOOLEAN NOT NULL DEFAULT FALSE,
    source    TEXT NOT NULL DEFAULT 'seed' CHECK (source IN ('seed', 'user')),
    embedding vector(384)
);

CREATE TABLE query_log (
    id            SERIAL PRIMARY KEY,
    session_id    TEXT,
    question      TEXT NOT NULL,
    generated_sql TEXT,
    final_sql     TEXT,
    retries       INT NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,
    latency_ms    INT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE feedback (
    id           SERIAL PRIMARY KEY,
    query_log_id INT NOT NULL REFERENCES query_log(id),
    rating       SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    comment      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE eval_runs (
    id          SERIAL PRIMARY KEY,
    config      JSONB NOT NULL,
    dataset     TEXT NOT NULL,
    accuracy    DOUBLE PRECISION,
    n_questions INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX schema_docs_col_uidx ON schema_docs (db_id, table_name, column_name);
CREATE INDEX schema_docs_embedding_idx ON schema_docs USING hnsw (embedding vector_cosine_ops);
CREATE INDEX examples_embedding_idx    ON examples    USING hnsw (embedding vector_cosine_ops);
