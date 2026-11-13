"""Identity for a LAN-reachable server (plan decisions 1 and 2).

Real accounts. The first account, made on the server console, is the admin
(role "owner"); the admin creates every other login, from the admin panel or
the console, and hands over the username and password. There is no signup and
there are no invite codes. A disabled login is signed out at once. Passwords are scrypt-hashed with a per-user salt; sessions are
random tokens stored hashed, sent as an HttpOnly SameSite=Lax cookie; every
mutating request must also carry the CSRF token from a second, readable cookie.

Nobody creates an account from the web. The owner is created from the
server console (`anaplan-architect users create --owner`); the web layer
decides what a server with no accounts serves (open on localhost, closed on
the network). That is how an install made before identity keeps working
for its one user without ever offering a signup to a stranger.
"""
from __future__ import annotations
import datetime, hashlib, hmac, secrets
from .db import Db, now

SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=64)
SESSION_DAYS = 30
DEFAULT_CAP_USD = 2.0        # the spend cap a new login starts with (ARCHITECT_DEFAULT_CAP_USD overrides); the admin has none
ROLES = ("owner", "member")


MAX_FAILS_PER_NAME = 5          # wrong passwords for one name inside the window before that name is refused
MAX_FAILS_PER_ADDRESS = 20      # failures from one address, whatever names it tried
FAIL_WINDOW_MINUTES = 15


class TooManyAttempts(Exception):
    """Sign-in refused without looking at the password: too many failures lately. `retry_after` is in seconds."""
    def __init__(self, retry_after: int):
        super().__init__("too many failed sign-ins: wait and try again"); self.retry_after = retry_after


def hash_password(pw: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or secrets.token_bytes(16)
    return hashlib.scrypt(pw.encode("utf-8"), salt=salt, **SCRYPT), salt


def verify_password(pw: str, pw_hash: bytes, salt: bytes) -> bool:
    return hmac.compare_digest(hashlib.scrypt(pw.encode("utf-8"), salt=salt, **SCRYPT), pw_hash)


def _h(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _later(days: int) -> str:
    return (datetime.datetime.now() + datetime.timedelta(days=days)).isoformat(timespec="seconds")


def _user(row: dict | None) -> dict | None:
    if not row:
        return None
    return {k: row[k] for k in ("id", "workspace_id", "email", "name", "role", "created", "last_seen")} | {"disabled": bool(row["disabled"]),
                                                                                                         "spend_cap_usd": row.get("spend_cap_usd")}


def no_accounts(db: Db) -> bool:
    return db.one("SELECT 1 FROM users LIMIT 1") is None


setup_mode = no_accounts     # older name


def default_cap() -> float | None:
    import os
    raw = os.environ.get("ARCHITECT_DEFAULT_CAP_USD")
    if raw is None or raw == "":
        return DEFAULT_CAP_USD
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_CAP_USD
    return v if v > 0 else None


def generate_password() -> str:
    """A password to hand over: four groups of letters and digits, easy to read out."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))


def create_user(db: Db, workspace_id: str, email: str, name: str, pw: str, role: str = "member", by: str | None = None, cap_usd="default") -> dict:
    """A login made by the admin (console or admin panel). `email` is the username: an email address or a plain name."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    email, name = _check(email, pw, name)
    if db.one("SELECT 1 FROM users WHERE email=?", email):
        raise ValueError("an account with that email already exists")
    h, salt = hash_password(pw)
    uid = "u-" + secrets.token_hex(6)
    cap = (None if role == "owner" else default_cap()) if cap_usd == "default" else cap_usd
    db.run("INSERT INTO users(id, workspace_id, email, name, pw_hash, pw_salt, role, created, spend_cap_usd) VALUES (?,?,?,?,?,?,?,?,?)",
           uid, workspace_id, email, name, h, salt, role, now(), cap)
    db.audit(workspace_id, "user.create", uid, {"email": email, "role": role, "via": "admin" if by else "console"}, by)
    return _user(db.one("SELECT * FROM users WHERE id=?", uid))


def _check(email: str, pw: str, name: str) -> tuple[str, str]:
    email = (email or "").strip().lower()
    if len(email) < 3 or len(email) > 200 or any(ch.isspace() for ch in email):
        raise ValueError("username: three characters or more, no spaces (an email address works)")
    if len(pw or "") < 10:
        raise ValueError("password: ten characters or more")
    return email, (name or "").strip()[:120] or email.split("@")[0]


def create_owner(db: Db, workspace_id: str, email: str, name: str, pw: str, workspace_name: str = "") -> dict:
    """The first account, from the console. Refuses once any account exists (a second owner is promoted, not created)."""
    if not no_accounts(db):
        raise PermissionError("this server already has an owner; promote another account instead")
    with db.tx():
        u = create_user(db, workspace_id, email, name, pw, role="owner")
        from . import access
        access.adopt_orphans(db, u["id"])          # what was made before there were logins is the first admin's
        if workspace_name.strip():
            db.run("UPDATE workspaces SET name=? WHERE id=?", workspace_name.strip()[:120], workspace_id)
    return u


# what an unknown name is checked against, so that it costs exactly what a real one costs: one password hash
_NOBODY_SALT = b"anaplan-architect"
_NOBODY_HASH = hashlib.scrypt(b"no such login", salt=_NOBODY_SALT, **SCRYPT)


def _since() -> str:
    return (datetime.datetime.now() - datetime.timedelta(minutes=FAIL_WINDOW_MINUTES)).isoformat(timespec="seconds")


def _held(db: Db, key: str, limit: int) -> int:
    """Seconds this key must still wait, or 0. Held while it has `limit` failures inside the window."""
    rows = db.q("SELECT at FROM login_attempts WHERE key=? AND at>=? ORDER BY at", key, _since())
    if len(rows) < limit:
        return 0
    free_at = datetime.datetime.fromisoformat(rows[len(rows) - limit]["at"]) + datetime.timedelta(minutes=FAIL_WINDOW_MINUTES)
    return max(1, int((free_at - datetime.datetime.now()).total_seconds()) + 1)


def login(db: Db, email: str, pw: str, address: str | None = None) -> tuple[dict, str]:
    """Returns (user, session token). A wrong name and a wrong password fail the same way and cost the same: one
    password hash. After MAX_FAILS_PER_NAME failures for a name, or MAX_FAILS_PER_ADDRESS from an address, inside
    FAIL_WINDOW_MINUTES, sign-in is refused (TooManyAttempts) before the password is looked at."""
    name = (email or "").strip().lower()[:200]
    keys = [("u:" + name, MAX_FAILS_PER_NAME)] + ([("a:" + address, MAX_FAILS_PER_ADDRESS)] if address else [])
    wait = max(_held(db, k, n) for k, n in keys)
    if wait:
        raise TooManyAttempts(wait)
    row = db.one("SELECT * FROM users WHERE email=?", name)
    ok = verify_password(pw or "", row["pw_hash"], row["pw_salt"]) if row and row["pw_hash"] else (verify_password(pw or "", _NOBODY_HASH, _NOBODY_SALT) and False)
    if not ok:
        for k, _n in keys:
            db.run("INSERT INTO login_attempts(key, at) VALUES (?,?)", k, now())
        db.run("DELETE FROM login_attempts WHERE at<?", (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec="seconds"))
        raise PermissionError("email or password not recognised")
    db.run("DELETE FROM login_attempts WHERE key=?", "u:" + name)
    if row["disabled"]:
        raise PermissionError("this account is disabled")
    token = secrets.token_urlsafe(32)
    db.run("INSERT INTO sessions(token_hash, user_id, created, expires, last_seen) VALUES (?,?,?,?,?)", _h(token), row["id"], now(), _later(SESSION_DAYS), now())
    db.run("UPDATE users SET last_seen=? WHERE id=?", now(), row["id"])
    db.audit(row["workspace_id"], "user.login", row["id"], None, row["id"])
    return _user(row), token


def logout(db: Db, token: str | None) -> None:
    if token:
        db.run("DELETE FROM sessions WHERE token_hash=?", _h(token))


def user_for_token(db: Db, token: str | None) -> dict | None:
    if not token:
        return None
    s = db.one("SELECT * FROM sessions WHERE token_hash=?", _h(token))
    if not s or s["expires"] < now():
        return None
    row = db.one("SELECT * FROM users WHERE id=?", s["user_id"])
    if not row or row["disabled"]:
        return None
    if (s["last_seen"] or "") < now()[:13]:      # once an hour is plenty
        db.run("UPDATE sessions SET last_seen=? WHERE token_hash=?", now(), s["token_hash"])
        db.run("UPDATE users SET last_seen=? WHERE id=?", now(), row["id"])
    return _user(row)


def change_password(db: Db, uid: str, old: str, new: str) -> None:
    row = db.one("SELECT * FROM users WHERE id=?", uid)
    if not row or not verify_password(old or "", row["pw_hash"], row["pw_salt"]):
        raise PermissionError("current password not recognised")
    _check(row["email"], new, row["name"])
    h, salt = hash_password(new)
    db.run("UPDATE users SET pw_hash=?, pw_salt=? WHERE id=?", h, salt, uid)
    db.run("DELETE FROM sessions WHERE user_id=?", uid)           # every other session signs out
    db.audit(row["workspace_id"], "user.password", uid, None, uid)


def set_password(db: Db, uid: str, pw: str, by: str | None = None) -> None:
    """The admin resets a login's password: every session of that login signs out."""
    row = db.one("SELECT * FROM users WHERE id=?", uid)
    if not row:
        raise KeyError(uid)
    _check(row["email"], pw, row["name"])
    h, salt = hash_password(pw)
    db.run("UPDATE users SET pw_hash=?, pw_salt=? WHERE id=?", h, salt, uid)
    db.run("DELETE FROM sessions WHERE user_id=?", uid)
    db.audit(row["workspace_id"], "user.password_reset", uid, None, by)


def spent(db: Db, uid: str) -> float:
    """What a login has used, metered at list price (a flat-rate route is metered at the default model's list price)."""
    return round(db.one("SELECT COALESCE(SUM(usd),0) AS s FROM spend WHERE user_id=?", uid)["s"], 4)


def record_spend(db: Db, uid: str | None, usd: float, billed_usd: float = 0.0, kind: str = "answer", model: str = "", tokens_in: int = 0, tokens_out: int = 0) -> None:
    """One model call on a login's ledger. Nothing that is deleted later (a chat, a workspace) takes it off again."""
    if not uid:
        return
    db.run("INSERT INTO spend(user_id, at, kind, model, tokens_in, tokens_out, usd, billed_usd) VALUES (?,?,?,?,?,?,?,?)",
           uid, now(), kind, model or "", int(tokens_in or 0), int(tokens_out or 0), float(usd or 0), float(billed_usd or 0))


def over_cap(db: Db, user: dict | None) -> dict | None:
    """None when the login may ask; otherwise the cap and what was spent."""
    if not user or user.get("spend_cap_usd") is None:
        return None
    used = spent(db, user["id"])
    return {"cap_usd": user["spend_cap_usd"], "spent_usd": used} if used >= user["spend_cap_usd"] else None


def admin_table(db: Db, workspace_id: str) -> list[dict]:
    """One row per login for the admin panel: who signed in, when, and how much each has done. Every figure is a count
    over the store, so the panel and the store cannot disagree."""
    out = []
    for u in accounts(db, workspace_id):
        uid = u["id"]
        t = db.one("SELECT COUNT(*) AS n, MAX(created) AS last FROM turns WHERE author_id=?", uid)
        t |= db.one("SELECT COALESCE(SUM(billed_usd),0) AS cost, COALESCE(SUM(usd),0) AS metered FROM spend WHERE user_id=?", uid)       # the ledger, not the answers still in the store
        out.append(dict(u,
                        sign_ins=db.one("SELECT COUNT(*) AS n FROM audit WHERE action='user.login' AND user_id=?", uid)["n"],
                        workspaces=db.one("SELECT COUNT(*) AS n FROM estate_members WHERE user_id=?", uid)["n"],
                        uploads=db.one("SELECT COUNT(*) AS n FROM snapshots WHERE created_by=?", uid)["n"],
                        documents=db.one("SELECT COUNT(*) AS n FROM documents WHERE uploaded_by=?", uid)["n"],
                        chats=db.one("SELECT COUNT(*) AS n FROM conversations WHERE author_id=?", uid)["n"],
                        questions=t["n"], last_question=t["last"], cost_usd=round(t["cost"], 4), metered_usd=round(t["metered"], 4),
                        over_cap=u["spend_cap_usd"] is not None and t["metered"] >= u["spend_cap_usd"]))
    return out


def accounts(db: Db, workspace_id: str) -> list[dict]:
    return [_user(r) for r in db.q("SELECT * FROM users WHERE workspace_id=? ORDER BY created", workspace_id)]


def update_account(db: Db, uid: str, by: str, disabled: bool | None = None, role: str | None = None, cap_usd="keep") -> dict:
    row = db.one("SELECT * FROM users WHERE id=?", uid)
    if not row:
        raise KeyError(uid)
    if role is not None and role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if uid == by and (disabled or (role and role != "owner")):
        raise ValueError("you cannot disable or demote your own account")
    if role is not None:
        db.run("UPDATE users SET role=? WHERE id=?", role, uid)
    if cap_usd != "keep":
        if cap_usd is not None and float(cap_usd) < 0:
            raise ValueError("a cap is a positive amount, or none")
        db.run("UPDATE users SET spend_cap_usd=? WHERE id=?", None if cap_usd is None else float(cap_usd), uid)
    if disabled is not None:
        db.run("UPDATE users SET disabled=? WHERE id=?", 1 if disabled else 0, uid)
        if disabled:
            db.run("DELETE FROM sessions WHERE user_id=?", uid)
    db.audit(row["workspace_id"], "user.update", uid, {"disabled": disabled, "role": role, **({"cap_usd": cap_usd} if cap_usd != "keep" else {})}, by)
    return _user(db.one("SELECT * FROM users WHERE id=?", uid))


def csrf_token() -> str:
    return secrets.token_urlsafe(24)
