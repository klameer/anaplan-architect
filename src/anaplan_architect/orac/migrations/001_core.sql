-- Orac stage 1: workspace, users (rows arrive with identity), estates, the model
-- register, blobs, snapshots of export files, parse runs, settings, audit.

CREATE TABLE workspaces(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created TEXT NOT NULL
);

CREATE TABLE users(
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  email TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  pw_hash BLOB,
  pw_salt BLOB,
  role TEXT NOT NULL DEFAULT 'member',
  created TEXT NOT NULL,
  last_seen TEXT,
  disabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE estates(
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  name TEXT NOT NULL,
  created_by TEXT REFERENCES users(id),
  created TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE models(
  id TEXT PRIMARY KEY,
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT '',
  owner TEXT NOT NULL DEFAULT '',
  created_by TEXT REFERENCES users(id),
  created TEXT NOT NULL,
  seq INTEGER NOT NULL,                 -- display and folder order within the estate
  retired INTEGER NOT NULL DEFAULT 0,
  UNIQUE(estate_id, name)
);

CREATE TABLE model_aliases(
  model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,                  -- a phrase import action names use for this model
  PRIMARY KEY(model_id, alias)
);

CREATE TABLE blobs(
  sha256 TEXT PRIMARY KEY,
  bytes INTEGER NOT NULL,
  stored_at TEXT NOT NULL
);

CREATE TABLE snapshots(
  id TEXT PRIMARY KEY,
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  label TEXT NOT NULL DEFAULT '',
  created_by TEXT REFERENCES users(id),
  created TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('draft','processing','processed','active','failed','superseded')),
  activated_at TEXT,
  superseded_at TEXT,
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX snapshots_estate ON snapshots(estate_id, created);

CREATE TABLE snapshot_files(
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  model_id TEXT NOT NULL REFERENCES models(id),
  kind TEXT NOT NULL CHECK(kind IN ('line_items','actions','modules')),
  blob_sha TEXT NOT NULL REFERENCES blobs(sha256),
  original_name TEXT NOT NULL DEFAULT '',
  uploaded_at TEXT NOT NULL,
  problem TEXT,                         -- what validation found wrong, or NULL
  PRIMARY KEY(snapshot_id, model_id, kind)
);

CREATE TABLE parse_runs(
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  started TEXT NOT NULL,
  finished TEXT,
  status TEXT NOT NULL CHECK(status IN ('running','ok','failed','cancelled')),
  error TEXT,
  stats_json TEXT,
  coverage_json TEXT
);
CREATE INDEX parse_runs_snapshot ON parse_runs(snapshot_id, started);

CREATE TABLE settings(
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  key TEXT NOT NULL,
  value TEXT,
  PRIMARY KEY(workspace_id, key)
);

CREATE TABLE audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id TEXT NOT NULL,
  user_id TEXT,
  action TEXT NOT NULL,
  target TEXT NOT NULL DEFAULT '',
  detail_json TEXT,
  at TEXT NOT NULL
);
