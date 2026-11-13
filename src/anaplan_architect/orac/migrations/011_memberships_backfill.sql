-- A store that ran 010 before it carried the backfill: a workspace with no member used to go to whichever admin
-- touched it first, by a write inside the membership check. That write is gone (orac/access.py), so what it would
-- have done is done here, once: a workspace nobody is a member of goes to the admins that exist. With no logins yet,
-- this writes nothing, and the first admin takes such workspaces when it is created (orac/auth.py create_owner).
INSERT OR IGNORE INTO estate_members(estate_id, user_id, role, added)
SELECT e.id, u.id, 'owner', strftime('%Y-%m-%dT%H:%M:%S', 'now') FROM estates e JOIN users u ON u.workspace_id = e.workspace_id AND u.role = 'owner'
WHERE NOT EXISTS (SELECT 1 FROM estate_members m WHERE m.estate_id = e.id);
