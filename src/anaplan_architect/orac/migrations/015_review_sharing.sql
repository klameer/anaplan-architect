-- Security review of workspace sharing (2026-11-24).
--
-- Restored content is the restorer's: every author column of a restored row names the login that restored it. Who the
-- archive said wrote it is kept beside it as plain text, never as a login of this store.
ALTER TABLE conversations ADD COLUMN author_was TEXT;
ALTER TABLE turns ADD COLUMN author_was TEXT;
ALTER TABLE notes ADD COLUMN author_was TEXT;
ALTER TABLE documents ADD COLUMN uploaded_by_was TEXT;

-- What the asker of a turn let the outside tracer have at the time: off | structure | content. A later turn by
-- someone else in the same chat sends an earlier turn's words only when this says content.
ALTER TABLE turns ADD COLUMN trace_level TEXT;

-- An admin is in no team (a team's shared workspaces are its members' to read, never the operator's).
UPDATE users SET team_id=NULL WHERE role='owner';
