-- Orac stage 2: notes (with full-text search), conversations and turns in the store,
-- citations persisted per turn and per note, finding state on patterns.

CREATE TABLE notes(
  id TEXT PRIMARY KEY,
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT '',
  body TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('purpose','decision','constraint','procedure','conclusion')),
  status TEXT NOT NULL CHECK(status IN ('working_assumption','user_confirmed','superseded')),
  author_id TEXT REFERENCES users(id),
  confirmed_by TEXT REFERENCES users(id),
  confirmed_at TEXT,
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  superseded_by TEXT REFERENCES notes(id),
  origin_kind TEXT NOT NULL DEFAULT 'user',          -- user | answer | chat_tool | import
  origin_conversation_id TEXT,
  origin_turn_id TEXT
);
CREATE INDEX notes_estate ON notes(estate_id, status, type);

CREATE TABLE note_objects(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  scope TEXT NOT NULL CHECK(scope IN ('estate','model','module','line_item','rule')),
  model_id TEXT REFERENCES models(id),
  module TEXT,
  line_item TEXT,
  rule TEXT
);
CREATE INDEX note_objects_note ON note_objects(note_id);
CREATE INDEX note_objects_target ON note_objects(scope, model_id, module, line_item, rule);

CREATE TABLE note_sources(
  note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  citation_id TEXT NOT NULL,
  PRIMARY KEY(note_id, citation_id)
);

CREATE VIRTUAL TABLE notes_fts USING fts5(title, body, content='notes', content_rowid='rowid');
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO notes_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;
CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
  INSERT INTO notes_fts(notes_fts, rowid, title, body) VALUES ('delete', old.rowid, old.title, old.body);
END;
CREATE TRIGGER notes_au AFTER UPDATE OF title, body ON notes BEGIN
  INSERT INTO notes_fts(notes_fts, rowid, title, body) VALUES ('delete', old.rowid, old.title, old.body);
  INSERT INTO notes_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;

CREATE TABLE conversations(
  id TEXT PRIMARY KEY,
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  snapshot_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  author_id TEXT REFERENCES users(id),
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,
  scope_json TEXT,
  transcript_path TEXT                               -- the JSONL export kept beside the store
);
CREATE INDEX conversations_estate ON conversations(estate_id, updated);

CREATE TABLE turns(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  author_id TEXT REFERENCES users(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  tools_json TEXT,
  usage_json TEXT,
  cost_usd REAL NOT NULL DEFAULT 0,
  unverified_json TEXT,
  unchecked_json TEXT,
  created TEXT NOT NULL,
  UNIQUE(conversation_id, seq)
);

CREATE TABLE citations(
  id TEXT NOT NULL,
  owner_kind TEXT NOT NULL,                          -- turn | note
  owner_id TEXT NOT NULL,
  provenance TEXT NOT NULL,                          -- observed | user_confirmed | inferred | ai_proposed | not_established
  snapshot_id TEXT,
  model_id TEXT,
  kind TEXT,
  object_ref TEXT NOT NULL,
  source_ref TEXT,
  payload_json TEXT,
  PRIMARY KEY(id, owner_kind, owner_id)
);
CREATE INDEX citations_owner ON citations(owner_kind, owner_id);

CREATE TABLE finding_state(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  finding_key TEXT NOT NULL,
  state TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  author_id TEXT,
  snapshot_id TEXT,
  updated TEXT NOT NULL,
  UNIQUE(estate_id, finding_key)
);
