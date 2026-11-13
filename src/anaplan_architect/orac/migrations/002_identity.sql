-- Orac stage 1, identity: invite codes and login sessions. Users came with 001.

CREATE TABLE invites(
  code_hash TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  created_by TEXT REFERENCES users(id),
  created TEXT NOT NULL,
  expires TEXT NOT NULL,
  used_by TEXT REFERENCES users(id),
  used_at TEXT
);

CREATE TABLE sessions(
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created TEXT NOT NULL,
  expires TEXT NOT NULL,
  last_seen TEXT
);
CREATE INDEX sessions_user ON sessions(user_id);
