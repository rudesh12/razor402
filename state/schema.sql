PRAGMA journal_mode = WAL;
PRAGMA synchronous  = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS txn (
  challenge_id   TEXT PRIMARY KEY,
  state          TEXT NOT NULL,
  rank           INTEGER NOT NULL,
  agent_kid      TEXT NOT NULL,
  item_id        TEXT NOT NULL,
  resource_hash  TEXT NOT NULL,
  amount_paise   INTEGER NOT NULL,
  price_basis    TEXT NOT NULL,
  rationale      TEXT,
  order_id       TEXT, payment_id TEXT, refund_id TEXT,
  settled_via    TEXT, payment_mode TEXT,
  attempts       INTEGER NOT NULL DEFAULT 0,
  next_at        INTEGER NOT NULL DEFAULT 0,
  lease_until    INTEGER NOT NULL DEFAULT 0,
  req_method     TEXT, req_path TEXT, req_query TEXT, req_body BLOB,
  resp_status    INTEGER, resp_body BLOB, resp_sha256 TEXT,
  fail_reason    TEXT,
  created_at     INTEGER NOT NULL,
  updated_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sweep ON txn(state, next_at, lease_until);
CREATE INDEX IF NOT EXISTS idx_agent_day ON txn(agent_kid, created_at);

CREATE TABLE IF NOT EXISTS jti_seen (
  jti TEXT PRIMARY KEY, challenge_id TEXT NOT NULL,
  resource_hash TEXT NOT NULL, seen_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS budget_reservations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_kid TEXT NOT NULL, challenge_id TEXT NOT NULL UNIQUE,
  amount_paise INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('HELD','CAPTURED','RELEASED')),
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_res_agent ON budget_reservations(agent_kid, created_at, status);

CREATE TABLE IF NOT EXISTS mandates (
  token TEXT PRIMARY KEY, agent_kid TEXT NOT NULL,
  blocked_paise INTEGER NOT NULL, debited_paise INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS passes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_kid TEXT NOT NULL, item_id TEXT NOT NULL,
  expires_at INTEGER NOT NULL, challenge_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pass ON passes(agent_kid, item_id, expires_at);

CREATE TABLE IF NOT EXISTS webhook_events (
  event_id TEXT PRIMARY KEY, event_type TEXT,
  challenge_id TEXT, raw_sha256 TEXT NOT NULL, received_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, challenge_id TEXT, event TEXT NOT NULL,
  from_state TEXT, to_state TEXT, to_rank INTEGER,
  actor TEXT NOT NULL, payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
  seq INTEGER PRIMARY KEY, entry_hash TEXT NOT NULL,
  signature TEXT NOT NULL, created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS po_drafts (
  po_number TEXT PRIMARY KEY,
  total_paise INTEGER NOT NULL,
  bom_sha256 TEXT NOT NULL,
  plan_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
  BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;

