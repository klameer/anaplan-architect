-- v0.2 P2: the line-item index. Written when a snapshot is first read for questions: a row per line item, a row per
-- reference the grammar found (with the function it sits in), a row per function a formula uses, and FTS5 over names,
-- formulas and notes. It answers counting and filtering questions across every model of a workspace without the
-- list ever entering the prompt. No embeddings.

CREATE TABLE li_index(
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  module TEXT NOT NULL,
  name TEXT NOT NULL,
  ref TEXT NOT NULL,                                 -- Module.Line Item
  format TEXT NOT NULL DEFAULT '',
  applies_to TEXT NOT NULL DEFAULT '',               -- |Dim A|Dim B| (the line item's own, else its module's)
  time_scale TEXT NOT NULL DEFAULT '',
  versions TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  formula TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  cells INTEGER NOT NULL DEFAULT 0,
  effort REAL,
  calculated INTEGER NOT NULL DEFAULT 0,
  parsed INTEGER NOT NULL DEFAULT 1,
  formula_len INTEGER NOT NULL DEFAULT 0,
  ifs INTEGER NOT NULL DEFAULT 0,
  depth INTEGER NOT NULL DEFAULT 0,                  -- nesting of the parsed formula
  uses INTEGER NOT NULL DEFAULT 0,                   -- line items it reads
  used_by INTEGER NOT NULL DEFAULT 0,                -- line items that read it
  PRIMARY KEY(snapshot_id, model, ref)
);
CREATE INDEX li_index_module ON li_index(snapshot_id, model, module);

CREATE TABLE li_refs(
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  from_ref TEXT NOT NULL,
  to_ref TEXT NOT NULL,                              -- Module.Line Item it reads
  to_module TEXT NOT NULL,
  fn TEXT NOT NULL DEFAULT ''                        -- the function or clause the reference sits in ('' at the top of the formula)
);
CREATE INDEX li_refs_to ON li_refs(snapshot_id, model, to_ref);
CREATE INDEX li_refs_tomod ON li_refs(snapshot_id, model, to_module);
CREATE INDEX li_refs_from ON li_refs(snapshot_id, model, from_ref);

CREATE TABLE li_funcs(
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  ref TEXT NOT NULL,
  fn TEXT NOT NULL,                                  -- upper case: IF, DIVIDE, SUM, LOOKUP, FINDITEM ...
  kind TEXT NOT NULL,                                -- function | clause | keyword
  n INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(snapshot_id, model, ref, fn, kind)
);
CREATE INDEX li_funcs_fn ON li_funcs(snapshot_id, fn);

CREATE VIRTUAL TABLE li_fts USING fts5(ref, formula, notes, content='li_index', content_rowid='rowid', tokenize='unicode61');
CREATE TRIGGER li_index_ai AFTER INSERT ON li_index BEGIN
  INSERT INTO li_fts(rowid, ref, formula, notes) VALUES (new.rowid, new.ref, new.formula, new.notes);
END;
CREATE TRIGGER li_index_ad AFTER DELETE ON li_index BEGIN
  INSERT INTO li_fts(li_fts, rowid, ref, formula, notes) VALUES ('delete', old.rowid, old.ref, old.formula, old.notes);
END;
