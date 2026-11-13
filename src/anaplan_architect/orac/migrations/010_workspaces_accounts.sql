-- v0.2 P5: one login, many workspaces. A membership row per (workspace, login); every route and chat tool is checked
-- against it in one place (orac/access.py). Logins are made by the admin only. A spend cap per login, metered at list
-- price even where the route is flat-rate, so a cap means the same on every provider.

CREATE TABLE estate_members(
  estate_id TEXT NOT NULL REFERENCES estates(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'owner',
  added TEXT NOT NULL,
  PRIMARY KEY(estate_id, user_id)
);
CREATE INDEX estate_members_user ON estate_members(user_id);

ALTER TABLE users ADD COLUMN spend_cap_usd REAL;          -- NULL: no cap
ALTER TABLE turns ADD COLUMN metered_usd REAL NOT NULL DEFAULT 0;
UPDATE turns SET metered_usd = cost_usd;

-- invite codes are gone: the admin creates each login and hands over the username and password
DROP TABLE IF EXISTS invites;

-- A store that already had logins (v0.1): every login saw every estate. Keep that: each existing login becomes a
-- member of each existing workspace. On a new store there are no logins yet and this writes nothing.
INSERT OR IGNORE INTO estate_members(estate_id, user_id, role, added)
SELECT e.id, u.id, 'owner', strftime('%Y-%m-%dT%H:%M:%S', 'now') FROM estates e JOIN users u ON u.workspace_id = e.workspace_id;
