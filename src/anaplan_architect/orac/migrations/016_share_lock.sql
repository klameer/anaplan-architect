-- Security review, third pass (2026-11-24). A workspace restored from a backup of a shared workspace that held other
-- people's content comes back unable to be shared with a team: every row in it is the restorer's now, so nothing else
-- would say that what a team-mate wrote is in it. The reason is kept here as text; the admin can lift it.
ALTER TABLE estates ADD COLUMN share_locked TEXT;
