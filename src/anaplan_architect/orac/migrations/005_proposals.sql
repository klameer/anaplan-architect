-- Orac stage 4: actions the architect proposes in conversation, or the owner types, kept beside the
-- deterministic plan and labelled as unconfirmed until the owner records a state on them. Their state,
-- like every deterministic card's, lives in finding_state (keys proposal:<id> and action:<key>).

CREATE TABLE proposals(
  id TEXT PRIMARY KEY,
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  title TEXT NOT NULL,
  why TEXT NOT NULL DEFAULT '',
  steps_json TEXT NOT NULL DEFAULT '[]',
  done_when TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  objects_json TEXT NOT NULL DEFAULT '[]',
  citations_json TEXT NOT NULL DEFAULT '[]',
  origin_kind TEXT NOT NULL,            -- chat_tool | user
  author_id TEXT,
  conversation_id TEXT,
  turn_id TEXT,
  created TEXT NOT NULL,
  withdrawn_at TEXT,
  withdrawn_by TEXT
);
CREATE INDEX proposals_estate ON proposals(estate_id, created);
