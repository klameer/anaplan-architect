-- v0.2 P1: project documents in the workspace, read section by section, and what each answer was given.
-- A document is split into sections by heading at upload and gets a card (title, type, date, headings, a summary
-- written once, the objects it names). Search is FTS5 over sections plus the object links: no vectors, no embeddings.

CREATE TABLE documents(
  id TEXT PRIMARY KEY,                               -- d-xxxxxxxxxx
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  doc_type TEXT NOT NULL DEFAULT 'Document',
  filename TEXT NOT NULL,
  ext TEXT NOT NULL DEFAULT '',
  bytes INTEGER NOT NULL DEFAULT 0,
  blob_sha TEXT,
  doc_date TEXT,                                     -- a date read from the text or the name, else the upload date
  summary TEXT NOT NULL DEFAULT '',
  summary_by TEXT NOT NULL DEFAULT 'extract',        -- model | extract
  words INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1,
  replaces TEXT,                                     -- the id of the document this one replaced
  problem TEXT,                                      -- said on the card: no text found (a scanned PDF), a cut at the size cap
  uploaded_at TEXT NOT NULL,
  uploaded_by TEXT REFERENCES users(id)
);
CREATE INDEX documents_estate ON documents(estate_id, uploaded_at);

CREATE TABLE doc_sections(
  id TEXT PRIMARY KEY,                               -- s-xxxxxxxxxx, a hash of (document, seq): stable for a document
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  heading TEXT NOT NULL DEFAULT '',
  level INTEGER NOT NULL DEFAULT 1,
  text TEXT NOT NULL,
  tokens INTEGER NOT NULL DEFAULT 0,
  UNIQUE(document_id, seq)
);

CREATE TABLE doc_section_objects(
  section_id TEXT NOT NULL REFERENCES doc_sections(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  kind TEXT NOT NULL,                                -- module | line_item
  ref TEXT NOT NULL,
  PRIMARY KEY(section_id, model, kind, ref)
);
CREATE INDEX doc_section_objects_ref ON doc_section_objects(ref);

CREATE VIRTUAL TABLE doc_sections_fts USING fts5(heading, text, content='doc_sections', content_rowid='rowid', tokenize='porter unicode61');
CREATE TRIGGER doc_sections_ai AFTER INSERT ON doc_sections BEGIN
  INSERT INTO doc_sections_fts(rowid, heading, text) VALUES (new.rowid, new.heading, new.text);
END;
CREATE TRIGGER doc_sections_ad AFTER DELETE ON doc_sections BEGIN
  INSERT INTO doc_sections_fts(doc_sections_fts, rowid, heading, text) VALUES ('delete', old.rowid, old.heading, old.text);
END;

-- What an answer was given (the context view), what it did (the run timeline), the blocks the page draws for its
-- question type, and the answer mode it was asked in.
ALTER TABLE turns ADD COLUMN context_json TEXT;
ALTER TABLE turns ADD COLUMN run_json TEXT;
ALTER TABLE turns ADD COLUMN blocks_json TEXT;
ALTER TABLE turns ADD COLUMN mode TEXT;
ALTER TABLE turns ADD COLUMN kind TEXT;

-- A login's own preferences (the default answer mode).
ALTER TABLE users ADD COLUMN prefs_json TEXT;
