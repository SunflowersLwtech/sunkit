-- claude-mesh relay schema v1
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS team (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  retention_days INTEGER NOT NULL DEFAULT 7,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES team(id),
  handle TEXT NOT NULL,
  display_name TEXT NOT NULL,
  public_key BLOB,
  created_at TEXT NOT NULL,
  disabled_at TEXT,
  last_active_at TEXT,   -- v2: updated on every authenticated request; drives auto-purge
  UNIQUE(team_id, handle)
);

CREATE TABLE IF NOT EXISTS token (
  id TEXT PRIMARY KEY,
  human_id TEXT NOT NULL REFERENCES human(id),
  token_hash BLOB NOT NULL UNIQUE,
  label TEXT NOT NULL,
  tier TEXT NOT NULL CHECK(tier IN ('human', 'admin')),
  created_at TEXT NOT NULL,
  revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_token_human ON token(human_id);

CREATE TABLE IF NOT EXISTS pair_code (
  code_hash BLOB PRIMARY KEY,
  human_id TEXT NOT NULL REFERENCES human(id),
  tier TEXT NOT NULL CHECK(tier IN ('human', 'admin')),
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message (
  id TEXT PRIMARY KEY,
  v INTEGER NOT NULL,
  team_id TEXT NOT NULL REFERENCES team(id),
  from_handle TEXT NOT NULL,
  to_handle TEXT NOT NULL,    -- human handle or '@team'
  in_reply_to TEXT,
  thread_root TEXT,
  kind TEXT NOT NULL CHECK(kind IN ('chat','presence_update','permission_request','permission_verdict')),
  content TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  sent_at TEXT NOT NULL,
  delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_message_team_id ON message(team_id, id);
CREATE INDEX IF NOT EXISTS idx_message_to_handle ON message(team_id, to_handle, id);
CREATE INDEX IF NOT EXISTS idx_message_thread ON message(thread_root);

CREATE TABLE IF NOT EXISTS idempotency_key (
  key_hash BLOB PRIMARY KEY,
  token_id TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  team_id TEXT NOT NULL REFERENCES team(id),
  at TEXT NOT NULL,
  actor_human_id TEXT,
  event TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_team_at ON audit_log(team_id, at);

INSERT OR IGNORE INTO schema_version(version) VALUES (1);
INSERT OR IGNORE INTO schema_version(version) VALUES (2);
