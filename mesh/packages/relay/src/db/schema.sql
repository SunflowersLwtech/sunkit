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

-- v4: the A2A ledger. Additive only, so an older relay image runs on this file unchanged.
-- Role and workgroup are bound to a token, never to a session (session ids are visible to the team).
-- No foreign key on token_id: an older relay deletes tokens without knowing this table exists.
CREATE TABLE IF NOT EXISTS token_grant (
  token_id TEXT PRIMARY KEY,
  role TEXT NOT NULL CHECK(role IN ('worker','orchestrator','observer','executor')),
  workgroup TEXT NOT NULL,
  visible_json TEXT NOT NULL DEFAULT '[]',
  machine TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES team(id),
  workgroup TEXT NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('submitted','working','input_required','auth_required','completed','failed','canceled','rejected')),
  progress TEXT,
  reason TEXT,
  assignee_session TEXT,
  assignee_name TEXT,
  assignee_machine TEXT,
  assignee_token TEXT,
  dispatcher_session TEXT,
  dispatcher_name TEXT,
  dispatcher_token TEXT NOT NULL,
  parent_task TEXT,
  depth INTEGER NOT NULL,
  prompt_sha256 TEXT,
  artifacts_json TEXT NOT NULL DEFAULT '[]',
  seq INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deadline TEXT,
  ended_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_team_seq ON task(team_id, seq);

-- One counter per team: every task change takes the next value, so `since_seq` resumes a snapshot.
CREATE TABLE IF NOT EXISTS task_seq (
  team_id TEXT PRIMARY KEY REFERENCES team(id),
  seq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lease (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES team(id),
  workgroup TEXT NOT NULL,
  name TEXT NOT NULL,
  holder_session TEXT NOT NULL,
  holder_name TEXT NOT NULL,
  holder_machine TEXT,
  holder_token TEXT NOT NULL,
  task_id TEXT,
  note TEXT,
  ttl_s INTEGER NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  renew_count INTEGER NOT NULL DEFAULT 0,
  renewed_s INTEGER NOT NULL DEFAULT 0,
  released_at TEXT,
  release_reason TEXT
);
-- At most one unreleased row per name; an expired one is released (reason 'expire') before a new acquire.
CREATE UNIQUE INDEX IF NOT EXISTS idx_lease_live ON lease(team_id, name) WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_lease_holder ON lease(holder_session) WHERE released_at IS NULL;

INSERT OR IGNORE INTO schema_version(version) VALUES (1);
INSERT OR IGNORE INTO schema_version(version) VALUES (2);
