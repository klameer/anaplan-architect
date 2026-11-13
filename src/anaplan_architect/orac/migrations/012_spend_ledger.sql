-- What each login has spent, as a ledger of its own: one row per model call, written when the call returns. It has no
-- foreign key to a chat, an answer or a workspace on purpose: deleting those must not give budget back. The spend cap
-- reads this table, and so does the admin panel.
CREATE TABLE spend(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,                             -- the login; kept even if the login is later disabled
  at TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'answer',               -- answer | summary (a document card written at upload)
  model TEXT NOT NULL DEFAULT '',
  tokens_in INTEGER NOT NULL DEFAULT 0,              -- input, cache reads and cache writes together
  tokens_out INTEGER NOT NULL DEFAULT 0,
  usd REAL NOT NULL DEFAULT 0,                       -- metered at list price, whatever the route bills
  billed_usd REAL NOT NULL DEFAULT 0                 -- what the route bills (zero on a flat-rate route)
);
CREATE INDEX spend_user ON spend(user_id, at);

-- what was spent before the ledger existed: one row per answer still in the store
INSERT INTO spend(user_id, at, kind, usd, billed_usd)
SELECT author_id, created, 'answer', COALESCE(metered_usd, 0), COALESCE(cost_usd, 0) FROM turns WHERE author_id IS NOT NULL;
