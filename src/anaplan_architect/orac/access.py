"""Who may see which workspace (v0.2 P5; teams and sharing 2026-11-24). One login has many workspaces; a workspace is
an isolated unit. Isolation is in name only: one SQLite file, and one check, made here, that every request goes
through before its handler runs. A Private workspace is its member rows' (the login that made or restored it). A
Shared workspace belongs to the team it is shared with: a login is a member while it is in that team, and only then,
its maker included. A team is a company: Shared never means every login on the instance, and never the admin. A request that names a workspace, or anything that lives in one (a chat, an
upload, a model, a note, a document, an answer, a citation), is answered only to a member; to anyone else the thing
does not exist (404, never 403: the id is not confirmed).

In the store a workspace is an `estates` row (the name predates v0.2).
"""
from __future__ import annotations
from .db import Db, now

# the id in /api/<family>/<id>/... and how to find the workspace it lives in
LOOKUPS = {
    "conversations": "SELECT estate_id FROM conversations WHERE id=?",
    "snapshots": "SELECT estate_id FROM snapshots WHERE id=?",
    "models": "SELECT estate_id FROM models WHERE id=?",
    "notes": "SELECT estate_id FROM notes WHERE id=?",
    "documents": "SELECT estate_id FROM documents WHERE id=?",
    "turns": "SELECT c.estate_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
}
NOT_IDS = {"estates": {"create", "restore"}}
FAMILIES = ("estates", "citations", *LOOKUPS)


def citation_estates(db: Db, ident: str) -> list[str]:
    """Every workspace that holds a citation of this id, on an answer or on a note. An id is a hash of what it cites,
    so it says nothing about whose it is: two workspaces can hold the same one."""
    rows = db.q("SELECT DISTINCT c.estate_id FROM citations x JOIN turns t ON x.owner_kind='turn' AND t.id=x.owner_id JOIN conversations c ON c.id=t.conversation_id WHERE x.id=? "
                "UNION SELECT DISTINCT n.estate_id FROM citations x JOIN notes n ON x.owner_kind='note' AND n.id=x.owner_id WHERE x.id=?", ident, ident)
    return sorted(r["estate_id"] for r in rows)


def estate_for(db: Db, path: str, live_citation=None, member=None) -> tuple[bool, str | None]:
    """(scoped, workspace id) for a request path. `scoped` is True when the path names something that lives in a
    workspace; the id is None when that thing is not in the store. A citation id may be held by more than one
    workspace: `member(eid)` picks the one this login is in, so an id is only ever answered from a workspace of the
    asker's own (security review 2026-11-24, M3)."""
    parts = path.split("/")
    if len(parts) < 4 or parts[1] != "api" or parts[2] not in FAMILIES or not parts[3] or parts[3] in NOT_IDS.get(parts[2], ()):
        return False, None
    fam, ident = parts[2], parts[3]
    if fam == "estates":
        return True, ident
    if fam == "citations":
        found = citation_estates(db, ident)
        if not found and live_citation:
            live = live_citation(ident)
            found = list(live) if isinstance(live, (list, tuple, set)) else ([live] if live else [])
        if not found:
            return True, None
        mine = [e for e in found if member(e)] if member else found
        return True, (mine[0] if mine else found[0])
    row = db.one(LOOKUPS[fam], ident)
    return True, (row["estate_id"] if row else None)


def members(db: Db, eid: str) -> list[str]:
    return [r["user_id"] for r in db.q("SELECT user_id FROM estate_members WHERE estate_id=?", eid)]


def add_member(db: Db, eid: str, uid: str, role: str = "owner") -> None:
    db.run("INSERT OR IGNORE INTO estate_members(estate_id, user_id, role, added) VALUES (?,?,?,?)", eid, uid, role, now())


def is_member(db: Db, user: dict | None, eid: str) -> bool:
    """Private: a member row. Shared: in the team it is shared with, read from the store at the moment of asking, so a
    login moved out of a team (or disabled) is out at once, its maker like anyone else; and never an admin, who is in
    no team. Nothing else. This only reads: membership rows are written when a workspace is created or restored, when
    the first admin is created on a store that ran with no logins, and by the migrations; a team's access is never
    written as rows."""
    if user is None:
        return False
    e = db.one("SELECT visibility, team_id FROM estates WHERE id=?", eid)
    if e and e["visibility"] == "shared" and e["team_id"]:
        return db.one("SELECT 1 FROM users WHERE id=? AND team_id=? AND disabled=0 AND role<>'owner'", user["id"], e["team_id"]) is not None
    return db.one("SELECT 1 FROM estate_members m JOIN users u ON u.id=m.user_id WHERE m.estate_id=? AND m.user_id=? AND u.disabled=0", eid, user["id"]) is not None


# ---------- teams, and who a workspace is shared with ----------
VISIBILITY = ("private", "shared")


def shared(db: Db, eid: str) -> bool:
    e = db.one("SELECT visibility, team_id FROM estates WHERE id=?", eid)
    return bool(e and e["visibility"] == "shared" and e["team_id"])


def team_of(db: Db, uid: str | None) -> dict | None:
    """The team a login is in now: {"id", "name"}, or None."""
    if not uid:
        return None
    return db.one("SELECT t.id, t.name FROM users u JOIN teams t ON t.id=u.team_id WHERE u.id=?", uid)


def team_clean(name) -> str:
    """A team's name as it is kept: one form of each character, nothing invisible, single spaces."""
    import unicodedata
    if not isinstance(name, str):
        raise ValueError("a team's name is text")
    s = unicodedata.normalize("NFKC", name)
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Cc", "Co", "Cs", "Cn"))
    return unicodedata.normalize("NFC", " ".join(s.split()))[:80]


def team_key(name) -> str:
    """What makes two names the same team: the kept form, without case."""
    import unicodedata
    return unicodedata.normalize("NFKC", team_clean(name).casefold())


def _scripts(name: str) -> set[str]:
    import unicodedata
    out = set()
    for ch in name:
        if ch.isalpha():
            out.add((unicodedata.name(ch, "") or "?").split(" ")[0])
    return out


# characters that read as a Latin letter and are not one, and pairs of letters that read as one
_LOOKS = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d", "к": "k", "м": "m", "н": "h",
                        "т": "t", "в": "b", "α": "a", "ο": "o", "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t", "υ": "u", "ε": "e", "0": "o", "1": "l", "ı": "i"})


def team_looks(name) -> str:
    """What a name reads as at a glance: its key with look-alike letters folded to the Latin ones, the pairs that read as
    one letter joined, and punctuation and spaces dropped. Two different names with the same value here are confusable."""
    import unicodedata
    s = unicodedata.normalize("NFKD", team_key(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).translate(_LOOKS)
    s = s.replace("rn", "m").replace("vv", "w").replace("cl", "d").replace("l", "i")
    return "".join(ch for ch in s if ch.isalnum())


def find_team(db: Db, workspace_id: str, name) -> dict | None:
    """An existing team by its name, however it was typed (case, width, spaces, invisible characters). Never makes one."""
    key = team_key(name)
    if not key:
        return None
    return next((t for t in db.q("SELECT id, name FROM teams WHERE workspace_id=?", workspace_id) if team_key(t["name"]) == key), None)


class Confusable(ValueError):
    """A new team's name reads like an existing team's. Not refused for good: the admin is asked to confirm."""
    def __init__(self, new: str, existing: str):
        super().__init__(f"{new} reads very like the team that is already here, {existing}. If it is the same company, pick {existing} from the list. "
                         "If it really is another one, confirm and it is made")
        self.existing = existing


def create_team(db: Db, workspace_id: str, name, by: str | None = None, confirmed: bool = False) -> dict:
    """A new team: its own action, never a side effect of typing a name on a login. A name that reads as an existing
    team's is refused, and so is one that mixes alphabets (a Cyrillic letter inside a Latin word looks like a typo of
    nothing and is a different company to the store)."""
    import secrets
    clean = team_clean(name)
    if not clean:
        raise ValueError("a team needs a name")
    have = find_team(db, workspace_id, clean)
    if have:
        raise ValueError(f"there is already a team called {have['name']}: pick it from the list")
    if len(_scripts(clean)) > 1:
        raise ValueError("that name mixes letters from more than one alphabet, which reads as one company and is stored as another: type it in one alphabet")
    if not confirmed:
        looks = team_looks(clean)
        for t in db.q("SELECT name FROM teams WHERE workspace_id=?", workspace_id):
            if looks and team_looks(t["name"]) == looks:
                raise Confusable(clean, t["name"])
    tid = "t-" + secrets.token_hex(6)
    db.run("INSERT INTO teams(id, workspace_id, name, created, created_by) VALUES (?,?,?,?,?)", tid, workspace_id, clean, now(), by)
    db.audit(workspace_id, "team.create", tid, {"name": clean}, by)
    return {"id": tid, "name": clean}


def set_team(db: Db, uid: str, team_id: str | None, by: str | None = None) -> dict:
    """Put a login in a team, move it, or take it out. An admin is in no team. A shared workspace belongs to the team
    it is shared with: when its maker leaves that team it stays, the maker loses it like anyone else, and it has no
    maker until the admin names a team-mate (security review 2026-11-24, M1). Returns the workspaces left without one."""
    row = db.one("SELECT workspace_id, team_id, role FROM users WHERE id=?", uid)
    if not row:
        raise KeyError(uid)
    if team_id and row["role"] == "owner":
        raise ValueError("an admin is in no team: a team's shared workspaces are its members' to read, not the admin's. Use a second, ordinary login to work in a team")
    left = []
    with db.tx():
        if row["team_id"] and row["team_id"] != team_id:
            for e in db.q("SELECT id FROM estates WHERE visibility='shared' AND team_id=?", row["team_id"]):
                if creator(db, e["id"]) == uid:
                    db.run("UPDATE estates SET created_by=NULL WHERE id=?", e["id"])
                    db.run("DELETE FROM estate_members WHERE estate_id=?", e["id"])
                    db.audit(row["workspace_id"], "estate.maker", e["id"], {"from": uid, "to": None, "why": "the maker left the team it is shared with"}, by)
                    left.append(e["id"])
        db.run("UPDATE users SET team_id=? WHERE id=?", team_id, uid)
        db.audit(row["workspace_id"], "user.team", uid, {"from": row["team_id"], "to": team_id}, by)
    return {"without_maker": left}


def teams(db: Db, workspace_id: str) -> list[dict]:
    return db.q("SELECT t.id, t.name, t.created, (SELECT COUNT(*) FROM users u WHERE u.team_id=t.id) AS logins, "
                "(SELECT COUNT(*) FROM estates e WHERE e.team_id=t.id AND e.visibility='shared') AS workspaces FROM teams t WHERE t.workspace_id=? ORDER BY lower(t.name)", workspace_id)


def creator(db: Db, eid: str) -> str | None:
    """Who made the workspace: the one login that may share it, make it private again or delete it while it is shared.
    A workspace from before logins has no maker recorded: its first member row stands in. None when its maker left the
    team it is shared with: the admin stands in then, without reading it, until the admin names a team-mate."""
    r = db.one("SELECT created_by FROM estates WHERE id=?", eid)
    if r and r["created_by"]:
        return r["created_by"]
    m = db.one("SELECT user_id FROM estate_members WHERE estate_id=? ORDER BY added, rowid LIMIT 1", eid)
    return m["user_id"] if m else None


AUTHORED = (("conversations", "author_id", "estate_id=?"), ("notes", "author_id", "estate_id=?"), ("documents", "uploaded_by", "estate_id=?"),
            ("snapshots", "created_by", "estate_id=?"), ("models", "created_by", "estate_id=?"), ("proposals", "author_id", "estate_id=?"),
            ("finding_state", "author_id", "estate_id=?"), ("turns", "author_id", "conversation_id IN (SELECT id FROM conversations WHERE estate_id=?)"))


def authors(db: Db, eid: str) -> set[str]:
    """Every login that put something into the workspace: a chat, a question, a note, a document, an upload, a decision."""
    out: set[str] = set()
    for table, col, where in AUTHORED:
        out |= {r["a"] for r in db.q(f"SELECT DISTINCT {col} AS a FROM {table} WHERE {where} AND {col} IS NOT NULL", eid)}
    return out


def outside(db: Db, eid: str, team_id: str) -> int:
    """How many of the workspace's authors are not in this team now."""
    ids = sorted(authors(db, eid))
    if not ids:
        return 0
    inside = {r["id"] for r in db.q(f"SELECT id FROM users WHERE team_id=? AND id IN ({','.join('?' * len(ids))})", team_id, *ids)}
    return len(set(ids) - inside)


def set_visibility(db: Db, eid: str, visibility: str, team_id: str | None, by: str | None = None) -> dict:
    """Private, or Shared with one team. A workspace goes back to the team it was last shared with, or to a team that
    every one of its authors is in now, and to no other: what a team-mate wrote does not follow the maker to another
    company (M1). A private workspace keeps the team it was last shared with for that reason only; nobody is a member
    through it. Returns the names of the logins who had it and no longer do."""
    if visibility not in VISIBILITY:
        raise ValueError("visibility is private or shared")
    if visibility == "shared" and not team_id:
        raise ValueError("a workspace is shared with a team: this login is in no team, so there is nobody to share it with")
    e = db.one("SELECT workspace_id, visibility, team_id, share_locked FROM estates WHERE id=?", eid)
    if not e:
        raise KeyError(eid)
    if visibility == "shared" and e["share_locked"]:
        raise ValueError(f"this workspace cannot be shared with a team: {e['share_locked']}. Everything in it is under your name now, so nothing else would say whose it was. "
                         "The admin can allow it")
    if visibility == "shared" and e["team_id"] != team_id:
        n = outside(db, eid, team_id)
        if n:
            t = db.one("SELECT name FROM teams WHERE id=?", team_id)
            raise ValueError(f"this workspace holds chats, notes or documents added by {n} {'person' if n == 1 else 'people'} outside {t['name'] if t else 'that team'}, "
                             f"so it cannot be shared with {t['name'] if t else 'it'}. Make a new workspace for the new team")
    before = set(member_names(db, eid))
    db.run("UPDATE estates SET visibility=?, team_id=? WHERE id=?", visibility, team_id if visibility == "shared" else e["team_id"], eid)
    db.audit(e["workspace_id"], "estate.visibility", eid, {"from": e["visibility"], "to": visibility, "team": team_id if visibility == "shared" else None}, by)
    return {"lost": sorted(before - set(member_names(db, eid)))}


def allow_sharing(db: Db, eid: str, by: str | None = None) -> None:
    """The admin lifts the lock a restore put on a workspace (it came from a backup that held other people's content)."""
    e = db.one("SELECT workspace_id, share_locked FROM estates WHERE id=?", eid)
    if not e:
        raise KeyError(eid)
    db.run("UPDATE estates SET share_locked=NULL WHERE id=?", eid)
    db.audit(e["workspace_id"], "estate.share_unlocked", eid, {"was": e["share_locked"]}, by)


def set_maker(db: Db, eid: str, uid: str, by: str | None = None) -> None:
    """The admin names the maker of a shared workspace: a login that is in the team it is shared with."""
    e = db.one("SELECT workspace_id, visibility, team_id, created_by FROM estates WHERE id=?", eid)
    if not e:
        raise KeyError(eid)
    if e["visibility"] != "shared" or not e["team_id"]:
        raise ValueError("a private workspace is its maker's alone: there is nobody else to give it to")
    u = db.one("SELECT id, name FROM users WHERE id=? AND team_id=? AND disabled=0 AND role<>'owner'", uid, e["team_id"])
    if not u:
        raise ValueError("the maker of a shared workspace is a login in the team it is shared with")
    with db.tx():
        db.run("UPDATE estates SET created_by=? WHERE id=?", uid, eid)
        db.run("DELETE FROM estate_members WHERE estate_id=?", eid)
        add_member(db, eid, uid)
        db.audit(e["workspace_id"], "estate.maker", eid, {"from": e["created_by"], "to": uid}, by)


def member_names(db: Db, eid: str) -> list[str]:
    """Everyone who can open the workspace now, by name: a private one's member rows, or the team a shared one is shared with."""
    e = db.one("SELECT visibility, team_id FROM estates WHERE id=?", eid)
    if e and e["visibility"] == "shared" and e["team_id"]:
        rows = db.q("SELECT name FROM users WHERE team_id=? AND disabled=0 AND role<>'owner'", e["team_id"])
    else:
        rows = db.q("SELECT u.name FROM estate_members m JOIN users u ON u.id=m.user_id WHERE m.estate_id=? AND u.disabled=0", eid)
    return sorted({r["name"] for r in rows}, key=str.lower)


def describe(db: Db, user: dict | None, eid: str) -> dict:
    """What a member is told about who can see a workspace, before they type anything into it."""
    e = db.one("SELECT e.visibility, e.team_id, e.share_locked, t.name AS team FROM estates e LEFT JOIN teams t ON t.id=e.team_id WHERE e.id=?", eid) or {"visibility": "private", "team": None}
    maker = creator(db, eid)
    mrow = db.one("SELECT name FROM users WHERE id=?", maker) if maker else None
    mine = bool(user) and maker == user["id"]
    my_team = team_of(db, user["id"]) if user else None
    shared = e["visibility"] == "shared" and bool(e.get("team"))
    return {"visibility": "shared" if shared else "private", "team": e["team"] if shared else None, "creator": mrow["name"] if mrow else None, "mine": mine,
            "can_change": mine or bool(user and user.get("role") == "owner"), "can_share": bool(my_team) and mine and not e.get("share_locked"),
            "share_locked": e.get("share_locked") or None, "my_team": my_team["name"] if my_team else None,
            "members": member_names(db, eid),
            "chats": (f"Everyone in {e['team']} can read and add to the chats, documents and notes of this workspace. Each one shows who asked or added it."
                      if shared else "Only you can see the chats, documents and notes of this workspace.")}


def adopt_orphans(db: Db, uid: str) -> int:
    """Workspaces nobody is a member of (made while the store ran with no logins) go to this login. Called once, when
    the first admin is created."""
    rows = db.q("SELECT id FROM estates WHERE id NOT IN (SELECT estate_id FROM estate_members)")
    for r in rows:
        add_member(db, r["id"], uid)
    return len(rows)


def visible(db: Db, user: dict | None, estates: list[dict]) -> list[dict]:
    """The workspaces of a list that this login is a member of."""
    if user is None:
        return estates
    return [e for e in estates if is_member(db, user, e["id"])]
