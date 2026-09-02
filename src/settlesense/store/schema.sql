-- SettleSense storage schema. See docs/adr/ADR-003.
-- Plain SQL types only: no SQLite-specific constructs, so the move to
-- Postgres is a connection-string change. Runs are append-only.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    batch_id        TEXT NOT NULL,
    engine_version  TEXT NOT NULL,
    rules_version   TEXT NOT NULL,
    config_json     TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_rows (
    row_hash    TEXT NOT NULL,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    table_name  TEXT NOT NULL,
    natural_id  TEXT NOT NULL,
    raw_json    TEXT NOT NULL,
    duplicate_of TEXT,
    PRIMARY KEY (run_id, table_name, row_hash)
);

CREATE TABLE IF NOT EXISTS validation_errors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    source_file TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    field       TEXT,
    reason      TEXT NOT NULL,
    raw_row     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_results (
    reconciliation_id TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL REFERENCES runs(run_id),
    payment_id        TEXT NOT NULL,
    match_type        TEXT NOT NULL,
    match_score       REAL NOT NULL,
    expected_net      INTEGER NOT NULL,
    actual_net        INTEGER,
    difference_amount INTEGER NOT NULL,
    status            TEXT NOT NULL,
    reason_code       TEXT,
    settled_amount    INTEGER NOT NULL,
    pending_amount    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS result_settlements (
    reconciliation_id TEXT NOT NULL REFERENCES reconciliation_results(reconciliation_id),
    settlement_id     TEXT NOT NULL,
    claimed_paise     INTEGER NOT NULL,
    PRIMARY KEY (reconciliation_id, settlement_id)
);

CREATE TABLE IF NOT EXISTS calc_steps (
    reconciliation_id TEXT NOT NULL REFERENCES reconciliation_results(reconciliation_id),
    seq               INTEGER NOT NULL,
    label             TEXT NOT NULL,
    expression        TEXT NOT NULL,
    inputs_json       TEXT NOT NULL,
    result_paise      INTEGER NOT NULL,
    PRIMARY KEY (reconciliation_id, seq)
);

CREATE TABLE IF NOT EXISTS evidence_refs (
    reconciliation_id TEXT NOT NULL REFERENCES reconciliation_results(reconciliation_id),
    table_name        TEXT NOT NULL,
    natural_id        TEXT NOT NULL,
    row_hash          TEXT NOT NULL,
    role              TEXT,
    PRIMARY KEY (reconciliation_id, table_name, natural_id)
);

CREATE TABLE IF NOT EXISTS ledger_findings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    order_id    TEXT NOT NULL,
    payment_id  TEXT,
    reason      TEXT NOT NULL,
    detail      TEXT NOT NULL,
    amount      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    name        TEXT NOT NULL,
    value       REAL NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS review_actions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    reconciliation_id TEXT NOT NULL REFERENCES reconciliation_results(reconciliation_id),
    actor             TEXT NOT NULL,
    action            TEXT NOT NULL,
    note              TEXT,
    created_at        TEXT NOT NULL
);

-- Reserved for the AI sidecar (ADR-001/ADR-005). Kept in the schema so the
-- foreign key exists, but the engine never writes here and truncating it
-- must change no number on any screen.
CREATE TABLE IF NOT EXISTS explanations (
    reconciliation_id  TEXT PRIMARY KEY REFERENCES reconciliation_results(reconciliation_id),
    source             TEXT NOT NULL,
    category           TEXT NOT NULL,
    summary            TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    needs_human_review INTEGER NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    model              TEXT,
    prompt_version     TEXT,
    grounded           INTEGER NOT NULL,
    created_at         TEXT NOT NULL
);

-- Content-addressed explanation cache: key = prompt_version + trace_hash +
-- row_hashes, so re-running an unchanged case costs nothing and cannot be
-- delayed by the network.
CREATE TABLE IF NOT EXISTS explanation_cache (
    cache_key      TEXT PRIMARY KEY,
    payload_json   TEXT NOT NULL,
    model          TEXT,
    prompt_version TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_results_run ON reconciliation_results(run_id);
CREATE INDEX IF NOT EXISTS idx_results_status ON reconciliation_results(run_id, status);
CREATE INDEX IF NOT EXISTS idx_evidence_recon ON evidence_refs(reconciliation_id);
