-- Workspace sharing (2026-11-24). A login belongs to at most one team (a company): the admin sets it. A workspace is
-- Private (its maker only, as before) or Shared with one team: every login in that team is then a member, for as long
-- as it is in the team. Membership stays one check (orac/access.py): a member row, or a shared workspace whose team is
-- the login's team. Nothing is copied into estate_members for a team, so leaving a team ends access at once.
--
-- A store from before this: every workspace Private, every login without a team.

CREATE TABLE teams(
  id TEXT PRIMARY KEY,                               -- t-xxxxxxxxxxxx
  workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  name TEXT NOT NULL,
  created TEXT NOT NULL,
  created_by TEXT REFERENCES users(id)
);
CREATE UNIQUE INDEX teams_name ON teams(workspace_id, lower(name));

ALTER TABLE users ADD COLUMN team_id TEXT REFERENCES teams(id);
ALTER TABLE estates ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private';      -- private | shared
ALTER TABLE estates ADD COLUMN team_id TEXT REFERENCES teams(id);              -- the team a shared workspace is shared with
CREATE INDEX estates_team ON estates(team_id);
