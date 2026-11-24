"""Backup and restore of one estate, without credentials.

The archive is a zip: manifest.json; one JSON file per table slice that belongs
to the estate (register, snapshots with their files and parse runs, notes with
objects and sources, conversations with turns, the citations those turns and
notes own, finding state, proposals); the blobs the snapshots reference,
content-addressed, so a corrupt copy is caught on restore; and the .architect
folder's transcripts and reviews. Left out on purpose: users, password hashes,
sessions, invite codes, settings and the audit log. people.json carries id, name
and role (no email) so a reader can tell who was who.

A backup is a file its owner can edit, so a restore trusts nothing in it that
could reach outside the new workspace (security review 2026-11-24):

- The workspace gets an id, and so a folder, that this server mints. The id in
  the archive is never used as a folder name: on a disk that ignores case a
  variant of somebody's id would otherwise be their folder.
- Every id is made again by this server: the workspace's, and those of every
  upload, chat, answer, note, document, section, proposal and citation in it,
  wherever they appear, in the rows and in the text of the answers. So a chip
  in an old answer still opens (it carries the new id of the same thing), no id
  in an archive can collide with one in the store, a backup can be restored
  beside the workspace it was taken from, and a restore can neither learn that
  an id exists nor block someone else's (security review 2026-11-24, third
  pass). Ids in the archive must be in the shape this server makes, so that
  one cannot be an ordinary word of the text.
- Tables are read with a limit on what they may hold; an export file is
  streamed to disk and capped.
- Everything restored is the restorer's: every author column names the login
  that restored it. Who the archive says wrote it is kept beside it as text.
"""
from __future__ import annotations
import hashlib, json, re, sqlite3, zipfile
from zlib import error as zlib_error
from pathlib import Path
from .db import Db, now, new_id
from .blobs import BlobStore
from . import estates as reg

FORMAT = 1
KIND = "anaplan-architect-estate"
EXCLUDED = ("users", "sessions", "invites", "settings", "audit")
USER_COLS = {"estates": ("created_by",), "models": ("created_by",), "snapshots": ("created_by",), "notes": ("author_id", "confirmed_by", "reviewed_by"),
             "conversations": ("author_id",), "turns": ("author_id",), "finding_state": ("author_id",), "proposals": ("author_id", "withdrawn_by"),
             "documents": ("uploaded_by",)}
# restore order; blobs are written to the store, not inserted as rows
TABLES = ("estates", "models", "model_aliases", "blobs", "snapshots", "snapshot_files", "parse_runs", "notes", "note_objects", "note_sources",
          "conversations", "turns", "citations", "finding_state", "proposals", "documents", "doc_sections", "doc_section_objects")
AUTO_ID = ("finding_state", "note_objects")        # AUTOINCREMENT keys are reassigned on restore
PATH_IDS = ("estates", "snapshots", "models", "conversations")   # ids that become folder or file names on restore
MAX_TABLE_BYTES = 64 * 1024 * 1024          # one table of an archive, unzipped
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024   # everything in an archive, unzipped


def max_blob_bytes() -> int:
    """One export file of an archive, unzipped: what an upload of exports may be (ARCHITECT_MAX_MB). A zip entry of a
    few hundred KB can claim to open into gigabytes."""
    from .snapshots import MAX_MB
    return int(MAX_MB * 1024 * 1024)
# An id as this server makes them: lower-case letters and digits in groups joined by single hyphens. No capitals (two
# ids that differ only by case are one name on Windows and macOS), no dots (a trailing dot is dropped by Windows), no
# spaces, no separators.
_SAFE_ID = re.compile(r"^(?=.{1,64}$)[a-z0-9]+(?:-[a-z0-9]+){0,5}$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
SHAPED = ("estates", "snapshots", "models", "conversations", "turns", "notes", "documents", "doc_sections", "proposals", "parse_runs")   # every id of these is held to the shape
WAS = {"conversations": ("author_id", "author_was"), "turns": ("author_id", "author_was"), "notes": ("author_id", "author_was"), "documents": ("uploaded_by", "uploaded_by_was")}
# an id exactly as this server makes one: x-<hex>, a citation's c<10 hex>, or <date>-<time>-<hex>. Nothing else is taken
# as an id, so making ids again can never rewrite an ordinary word of an answer.
_GEN_ID = re.compile(r"^(?:[a-z]{1,2}-[0-9a-f]{6,16}|c[0-9a-f]{10}|\d{8}-\d{6}-[0-9a-f]{3,16})$")
_TOKEN = re.compile(r"[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*")
MAX_ROWS = 200_000                # rows in one table of an archive
MAX_BRACES = 1_500_000            # and how much structure its JSON may have: 60 MB of "{}," is twenty million objects
MAX_PEOPLE = 2_000
MAX_MANIFEST_BYTES = 1024 * 1024
LOCKED = "it was restored from a backup of a shared workspace that held other people's chats, notes or documents"


class AlreadyHere(ValueError):
    """An id in the archive is one the store holds. Said the same way whatever it is and whoever holds it."""


def safe_id(v) -> bool:
    return isinstance(v, str) and bool(_SAFE_ID.match(v)) and v not in _RESERVED and bool(_GEN_ID.match(v))


def _table(z: zipfile.ZipFile, name: str, names: set, max_bytes: int = MAX_TABLE_BYTES, max_rows: int = MAX_ROWS) -> list:
    """One JSON table of an archive: read in pieces, counted as it goes, and refused before it is parsed when it is
    bigger or has more structure than a table has. A zip entry of a few kilobytes can hold tens of megabytes of
    "{}," : parsed, that is gigabytes of objects (security review 2026-11-24)."""
    if name not in names:
        return []
    parts, size, braces = [], 0, 0
    with z.open(name) as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            size += len(chunk); braces += chunk.count(b"{") + chunk.count(b"[")
            if size > max_bytes or braces > MAX_BRACES:
                raise ValueError("the archive holds a table that is too large; it cannot be restored")
            parts.append(chunk)
    try:
        rows = json.loads(b"".join(parts).decode("utf-8"))
    except (ValueError, RecursionError):
        raise ValueError("the archive holds a table that cannot be read; it cannot be restored")
    if not isinstance(rows, list) or len(rows) > max_rows or not all(isinstance(r, dict) for r in rows):
        raise ValueError("the archive holds a table that is not a list of rows, or has too many; it cannot be restored")
    return rows


def _safe_rel(name: str, prefix: str) -> str | None:
    """An archive entry under prefix as a relative path that stays inside the folder it is written to; None when it would
    not (a '..' segment, an absolute path, a drive letter). Zip entry names are text anyone could have typed, not paths."""
    rel = name[len(prefix):].replace("\\", "/")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(p in ("", ".", "..") or ":" in p or p != p.rstrip(". ") or p.split(".")[0].lower() in _RESERVED for p in parts):
        return None
    return rel


def _app_version() -> str:
    try:
        from importlib.metadata import version
        return version("anaplan-architect")
    except Exception:
        return "unknown"


def collect(db: Db, eid: str) -> dict[str, list[dict]]:
    """Every row that belongs to the estate, table by table."""
    if not reg.get_estate(db, eid):
        raise KeyError(eid)
    t: dict[str, list[dict]] = {}
    t["estates"] = [dict(r, visibility="private", team_id=None) for r in db.q("SELECT * FROM estates WHERE id=?", eid)]     # who it is shared with never leaves
    t["models"] = db.q("SELECT * FROM models WHERE estate_id=? ORDER BY seq, created", eid)
    t["model_aliases"] = db.q("SELECT a.* FROM model_aliases a JOIN models m ON m.id=a.model_id WHERE m.estate_id=?", eid)
    t["blobs"] = db.q("SELECT DISTINCT b.* FROM blobs b JOIN snapshot_files f ON f.blob_sha=b.sha256 JOIN snapshots s ON s.id=f.snapshot_id WHERE s.estate_id=?", eid)
    t["snapshots"] = db.q("SELECT * FROM snapshots WHERE estate_id=? ORDER BY created", eid)
    t["snapshot_files"] = db.q("SELECT f.* FROM snapshot_files f JOIN snapshots s ON s.id=f.snapshot_id WHERE s.estate_id=?", eid)
    t["parse_runs"] = db.q("SELECT r.* FROM parse_runs r JOIN snapshots s ON s.id=r.snapshot_id WHERE s.estate_id=? ORDER BY r.started", eid)
    t["notes"] = db.q("SELECT * FROM notes WHERE estate_id=? ORDER BY created", eid)
    t["note_objects"] = db.q("SELECT o.* FROM note_objects o JOIN notes n ON n.id=o.note_id WHERE n.estate_id=? ORDER BY o.id", eid)
    t["note_sources"] = db.q("SELECT s.* FROM note_sources s JOIN notes n ON n.id=s.note_id WHERE n.estate_id=?", eid)
    t["conversations"] = db.q("SELECT * FROM conversations WHERE estate_id=? ORDER BY created", eid)
    t["turns"] = db.q("SELECT t.* FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE c.estate_id=? ORDER BY t.conversation_id, t.seq", eid)
    t["citations"] = db.q("SELECT x.* FROM citations x WHERE (x.owner_kind='turn' AND x.owner_id IN (SELECT t.id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE c.estate_id=?)) "
                          "OR (x.owner_kind='note' AND x.owner_id IN (SELECT id FROM notes WHERE estate_id=?))", eid, eid)
    t["finding_state"] = db.q("SELECT * FROM finding_state WHERE estate_id=? ORDER BY id", eid)
    t["proposals"] = db.q("SELECT * FROM proposals WHERE estate_id=? ORDER BY created", eid)
    # project documents (v0.2): the card, every section under its own id (answers cite sections by id) and the objects
    # each section names. The full-text index is rebuilt by the insert triggers on restore. A document's text lives in
    # its sections; the uploaded file itself is not kept, so there is no blob to carry.
    t["documents"] = db.q("SELECT * FROM documents WHERE estate_id=? ORDER BY uploaded_at, id", eid)
    t["doc_sections"] = db.q("SELECT s.* FROM doc_sections s JOIN documents d ON d.id=s.document_id WHERE d.estate_id=? ORDER BY s.document_id, s.seq", eid)
    t["doc_section_objects"] = db.q("SELECT o.* FROM doc_section_objects o JOIN doc_sections s ON s.id=o.section_id JOIN documents d ON d.id=s.document_id WHERE d.estate_id=?", eid)
    return t


def people(db: Db, tables: dict) -> list[dict]:
    """id, name and role of every account the rows name. No email, no hash."""
    ids = {r[c] for tb, cols in USER_COLS.items() for r in tables.get(tb, []) for c in cols if r.get(c)}
    if not ids:
        return []
    return db.q(f"SELECT id, name, role FROM users WHERE id IN ({','.join('?' * len(ids))}) ORDER BY name", *sorted(ids))


def export_estate(db: Db, blobs: BlobStore, data_root: str | Path, eid: str, out: str | Path, by: str | None = None) -> Path:
    tables = collect(db, eid)
    e = tables["estates"][0]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    counts = {k: len(v) for k, v in tables.items()}
    manifest = {"kind": KIND, "format": FORMAT, "exported_at": now(), "estate_id": eid, "name": e["name"], "app_version": _app_version(),
                "db_version": db.version, "counts": counts, "excluded": list(EXCLUDED),
                "active_snapshot": next((s["id"] for s in tables["snapshots"] if s["status"] == "active"), None)}
    # Said in the manifest, as plain fact: whether this workspace held anything added by a login other than the one
    # taking the backup (or was itself restored from one that did). A restore of such a backup comes back unable to be
    # shared with a team until the admin allows it. The file is its owner's to edit, so this limits re-sharing by the
    # honest route, not copying: whoever can read a workspace can always take what they read.
    from . import access
    manifest["held_others"] = bool(e.get("share_locked")) or bool(access.authors(db, eid) - ({by} if by else set()))
    arch = Path(data_root) / "estates" / eid / ".architect"
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        for name, rows in tables.items():
            z.writestr(f"tables/{name}.json", json.dumps(rows, ensure_ascii=False, default=str))
        z.writestr("people.json", json.dumps(people(db, tables), ensure_ascii=False))
        for b in tables["blobs"]:
            p = blobs.path(b["sha256"])
            if p.exists():
                z.write(p, f"blobs/{b['sha256']}")
        for sub in ("transcripts", "reviews"):
            d = arch / sub
            if d.is_dir():
                for f in sorted(d.rglob("*")):
                    if f.is_file() and "deleted" not in f.relative_to(d).parts:
                        z.write(f, f"architect/{sub}/{f.relative_to(d).as_posix()}")
    tmp.replace(out)
    db.audit(e["workspace_id"], "estate.backup", eid, {"file": out.name, "counts": counts}, by)
    return out


def inspect_archive(path: str | Path) -> dict:
    """What a backup holds, for a reader about to restore it: a bounded summary built from the manifest (name, counts,
    when it was taken), the model names and the people it names. Nothing of the archive is passed through as it is."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError):
        raise ValueError("that is not a zip file")
    try:
        with z:
            names = set(z.namelist())
            if "manifest.json" not in names:
                raise ValueError("not an architect backup: no manifest.json")
            # sizes as the archive declares them, before anything is unzipped: a small file can claim to open into gigabytes
            infos = z.infolist()
            if sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES or any(i.file_size > MAX_TABLE_BYTES for i in infos if not i.filename.startswith("blobs/")) \
                    or any(i.file_size > max_blob_bytes() for i in infos if i.filename.startswith("blobs/")) or z.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
                raise ValueError("the archive is too large once opened; it cannot be restored")
            blob_bytes = sum(i.file_size for i in infos if i.filename.startswith("blobs/"))
            # An export is text and packs perhaps twenty to one. A file of megabytes that packs a thousand to one is
            # padding: a few hundred KB of upload that costs what a few hundred MB of exports costs to read.
            if any(i.file_size > 8 * 1024 * 1024 and i.file_size > 200 * max(i.compress_size, 1) for i in infos):
                raise ValueError("the archive holds a file that is packed like no export is; it cannot be restored")
            try:
                with z.open("manifest.json") as f:
                    raw = json.loads(f.read(MAX_MANIFEST_BYTES + 1).decode("utf-8"))
            except (ValueError, RecursionError):
                raise ValueError("not an architect backup: its manifest cannot be read")
            if not isinstance(raw, dict) or raw.get("kind") != KIND:
                raise ValueError("not an architect estate backup")
            try:
                fmt = int(raw.get("format") or 0)
            except (TypeError, ValueError):
                raise ValueError("not an architect estate backup")
            if fmt > FORMAT:
                raise ValueError(f"backup format {fmt} is newer than this server reads ({FORMAT})")
            if not safe_id(raw.get("estate_id")) or not re.match(r"^\d{8}-\d{6}-[0-9a-f]{4,16}$", raw["estate_id"]):
                raise ValueError("the archive's workspace id is not in the shape this server makes; it cannot be restored")
            bad = [n for n in sorted(names) if n.startswith("architect/") and not n.endswith("/") and _safe_rel(n, "architect/") is None]
            if bad:
                raise ValueError(f"the archive holds a path that would leave its folder ({bad[0][:80]!r}); it cannot be restored")
            text = lambda v, n=120: " ".join(str(v if v is not None else "").split())[:n]
            blobs_listed = _table(z, "tables/blobs.json", names, max_rows=5000)
            counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
            people = [{"id": text(p.get("id"), 40), "name": text(p.get("name"), 80), "role": text(p.get("role"), 20)} for p in _table(z, "people.json", names, max_bytes=MAX_MANIFEST_BYTES, max_rows=MAX_PEOPLE)]
            m = {"kind": KIND, "format": fmt, "estate_id": raw["estate_id"], "name": text(raw.get("name"), 200), "exported_at": text(raw.get("exported_at"), 40),
                 "app_version": text(raw.get("app_version"), 40), "db_version": text(raw.get("db_version"), 12),
                 "active_snapshot": raw.get("active_snapshot") if safe_id(raw.get("active_snapshot")) else None,
                 "counts": {t: int(counts[t]) for t in TABLES if isinstance(counts.get(t), int) and not isinstance(counts.get(t), bool)},
                 "held_others": bool(raw.get("held_others")),
                 "blobs_missing": [text(b.get("sha256"), 64) for b in blobs_listed if f"blobs/{b.get('sha256')}" not in names][:50],
                 "blob_bytes": blob_bytes, "people": people,
                 "models": [text(x.get("name"), 80) for x in _table(z, "tables/models.json", names, max_rows=2000)][:200]}
    except (zipfile.BadZipFile, zlib_error, EOFError, OSError, KeyError, UnicodeDecodeError) as ex:      # a zip whose headers lie about what follows
        raise ValueError("that zip file is damaged; it cannot be restored")
    return m


# Every reference a row of an archive makes, and what it must point at: the archive's one estate, or a row of the
# named table in the same archive. A backup is a file its owner can edit; a row that names anything outside the
# archive (another workspace's snapshot, chat, note or model) would land in, or read from, a workspace that is not
# the restorer's. Such an archive is refused whole.
REFS = {
    "models": {"estate_id": "@estate"},
    "model_aliases": {"model_id": "models"},
    "snapshots": {"estate_id": "@estate"},
    "snapshot_files": {"snapshot_id": "snapshots", "model_id": "models", "blob_sha": "blobs"},
    "parse_runs": {"snapshot_id": "snapshots"},
    "notes": {"estate_id": "@estate", "superseded_by": "notes"},
    "note_objects": {"note_id": "notes", "model_id": "models"},
    "note_sources": {"note_id": "notes"},
    "conversations": {"estate_id": "@estate", "snapshot_id": "snapshots", "branched_from": "conversations"},
    "turns": {"conversation_id": "conversations"},
    "citations": {"snapshot_id": "snapshots"},
    "finding_state": {"estate_id": "@estate"},
    "proposals": {"estate_id": "@estate"},
    "documents": {"estate_id": "@estate", "replaces": None},
    "doc_sections": {"document_id": "documents"},
    "doc_section_objects": {"section_id": "doc_sections"},
}
_KEY = {"blobs": "sha256"}


def check_closed(tables: dict[str, list[dict]], eid: str) -> None:
    """Raise ValueError unless the archive is closed over itself: exactly one estate, the manifest's, and every row
    pointing only at that estate and at rows the archive itself carries."""
    def bad(what: str):
        raise ValueError(f"the archive holds {what} that is not part of this backup; it cannot be restored")
    est = tables.get("estates") or []
    if len(est) != 1 or str(est[0].get("id")) != eid:
        bad("a workspace row")
    have = {t: {str(r.get(_KEY.get(t, "id"))) for r in rows if isinstance(r, dict)} for t, rows in tables.items()}
    for t, rows in tables.items():
        for r in rows:
            if not isinstance(r, dict):
                bad(f"a {t} row")
            for col, target in (REFS.get(t) or {}).items():
                v = r.get(col)
                if v is None or v == "" or target is None:
                    continue
                if (str(v) != eid) if target == "@estate" else (str(v) not in have.get(target, ())):
                    bad(f"a {t.rstrip('s').replace('_', ' ')} pointing at {'another workspace' if target == '@estate' else 'a ' + target.rstrip('s').replace('_', ' ')}")
    turns, notes = have.get("turns", set()), have.get("notes", set())
    for r in tables.get("citations") or []:
        owner = str(r.get("owner_id"))
        if (r.get("owner_kind") == "turn" and owner not in turns) or (r.get("owner_kind") == "note" and owner not in notes) or r.get("owner_kind") not in ("turn", "note"):
            bad("a citation whose answer or note")
    for r in tables.get("note_sources") or []:                 # a note's source is a citation of the same archive, by id
        pass


def _cols(db: Db, table: str) -> set[str]:
    return {r["name"] for r in db.q(f"PRAGMA table_info({table})")}


def _remint(tables: dict[str, list[dict]], was: str, eid: str) -> dict[str, str]:
    """Old id -> new id for everything in the archive, made by this server. A section's id and a citation's id are
    what this server would have made for the same thing under the new ids (a citation's is a hash of its snapshot and
    what it cites), so the tools mint the same id for the same object afterwards."""
    import secrets
    from .evidence import cite_id
    from .documents import section_id
    ids: dict[str, str] = {was: eid}
    fresh = {"snapshots": new_id, "parse_runs": new_id, "models": lambda: "m-" + secrets.token_hex(4), "conversations": lambda: "c-" + secrets.token_hex(5),
             "turns": lambda: "t-" + secrets.token_hex(5), "notes": lambda: "n-" + secrets.token_hex(5), "documents": lambda: "d-" + secrets.token_hex(5),
             "proposals": lambda: "p-" + secrets.token_hex(5)}
    for t, make in fresh.items():
        for r in tables[t]:
            if r["id"] in ids:
                raise ValueError("the archive uses one id for two things; it cannot be restored")
            ids[r["id"]] = make()
    for r in tables["doc_sections"]:
        if r["id"] in ids or str(r.get("document_id")) not in ids:
            raise ValueError("the archive uses one id for two things; it cannot be restored")
        ids[r["id"]] = section_id(ids[str(r["document_id"])], int(r.get("seq") or 0))
    swap = lambda v: _swap(v, ids)
    for r in tables["citations"]:
        old = str(r.get("id"))
        if old in ids:
            continue
        sid, kind, model, ref = str(r.get("snapshot_id") or ""), str(r.get("kind") or ""), str(r.get("model_id") or ""), str(r.get("object_ref") or "")
        made_here = old == cite_id(sid, kind, model, ref)
        ids[old] = cite_id(ids.get(sid, sid), kind, model, swap(ref)) if made_here else "c" + secrets.token_hex(5)
    return ids


def _swap(v, ids: dict[str, str]):
    """A value with every old id in it replaced by its new one: a whole value that is an id, an id inside a text (an
    answer names the citations it rests on), and the same inside lists and dicts. Keys are never touched."""
    if isinstance(v, str):
        if v in ids:
            return ids[v]
        return _TOKEN.sub(lambda m: ids.get(m.group(0), m.group(0)), v) if len(v) >= 6 else v
    if isinstance(v, list):
        return [_swap(x, ids) for x in v]
    if isinstance(v, dict):
        return {k: _swap(x, ids) for k, x in v.items()}
    return v


def import_estate(db: Db, blobs: BlobStore, data_root: str | Path, path: str | Path, workspace_id: str, by: str | None = None, name: str | None = None) -> dict:
    """Restore an archive into this store as a new workspace, with every id in it made again by this server."""
    m = inspect_archive(path)
    was = m["estate_id"]                                   # the archive's own id: checked for consistency, never used
    eid = new_id()
    while reg.get_estate(db, eid) or (Path(data_root) / "estates" / eid).exists():
        eid = new_id()
    if m["blobs_missing"]:
        raise ValueError(f"the archive is missing {len(m['blobs_missing'])} of its export files; it cannot be restored")
    new_name = (name or "").strip() or None
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise ValueError("that is not a zip file")
    try:
      with z:
        names = set(z.namelist())
        tables = {t: _table(z, f"tables/{t}.json", names) for t in TABLES}
        check_closed(tables, was)
        for t in SHAPED:
            for r in tables[t]:
                if not safe_id(r.get("id")):
                    raise ValueError(f"a {t.rstrip('s').replace('_', ' ')} id in the archive is not in the shape this server makes ({str(r.get('id'))[:60]!r}); it cannot be restored")
        for r in tables["citations"]:
            if not isinstance(r.get("id"), str) or not r["id"] or len(r["id"]) > 64:
                raise ValueError("a citation id in the archive is not in the shape this server makes; it cannot be restored")
        used = {str(f.get("blob_sha")) for f in tables["snapshot_files"]}
        if any(str(b.get("sha256")) not in used for b in tables["blobs"]) or len({str(b.get("sha256")) for b in tables["blobs"]}) != len(tables["blobs"]):
            raise ValueError("the archive holds an export file that none of its uploads uses; it cannot be restored")
        try:
            said = {p["id"]: p["name"] for p in (m.get("people") or [])}
        except Exception:
            said = {}
        ids = _remint(tables, was, eid)
        for t in tables:                                  # every id, wherever a row carries one: as a value, or inside its text
            if t != "blobs":
                tables[t] = [{k: (v if (t == "snapshot_files" and k == "blob_sha") else _swap(v, ids)) for k, v in r.items()} for r in tables[t]]
        active = ids.get(m.get("active_snapshot") or "", None)
        written = 0
        cap = max_blob_bytes()
        import os, tempfile
        for b in tables["blobs"]:
            # To disk as it is unzipped, counted as it goes: never whole in memory, and never past the limit whatever the
            # zip's header claimed (security review 2026-11-24, M3).
            fd, tmp = tempfile.mkstemp(prefix="restore-", suffix=".part", dir=str(Path(path).parent))
            try:
                h, n = hashlib.sha256(), 0
                with os.fdopen(fd, "wb") as out, z.open(f"blobs/{b['sha256']}") as src:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        n += len(chunk)
                        if n > cap:
                            raise ValueError("the archive is too large once opened; it cannot be restored")
                        h.update(chunk); out.write(chunk)
                if h.hexdigest() != b["sha256"]:
                    raise ValueError(f"export file {str(b['sha256'])[:12]} in the archive does not match its hash: the archive is damaged")
                blobs.put_file(tmp)
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            written += 1
        arch = Path(data_root) / "estates" / eid / ".architect"
        files = {}                                        # the folder's files under their new names, their text with the new ids
        for n in names:
            if n.startswith("architect/") and not n.endswith("/"):
                rel = _safe_rel(n, "architect/")
                if rel is None:
                    continue                              # refused by inspect_archive already; belt and braces
                new_rel = _safe_rel("architect/" + _swap(rel, ids), "architect/") or rel
                files[new_rel] = n
        transcripts = {r[len("transcripts/"):] for r in files if r.startswith("transcripts/")}
        known = {r["id"] for r in db.q("SELECT id FROM users")}
        nulled = 0
        try:
          with db.tx() as c:
              c.execute("PRAGMA defer_foreign_keys=ON")
              for t in TABLES:
                  if t == "blobs":
                      continue
                  cols = _cols(db, t)
                  for r in tables[t]:
                      r = dict(r)
                      if t == "estates":
                          r["workspace_id"] = workspace_id
                          r["visibility"], r["team_id"] = "private", None      # whatever the archive says: a restore is the restorer's alone until they share it
                          r["share_locked"] = LOCKED if m.get("held_others") else None
                          if by:
                              r["created_by"] = by
                          if new_name:
                              r["name"] = new_name
                      if t == "snapshots" and r.get("status") == "processing":
                          r["status"] = "draft"
                      if t == "parse_runs" and r.get("status") == "running":
                          r["status"] = "cancelled"
                      if t == "conversations":
                          r["transcript_path"] = str(arch / "transcripts" / f"{r['id']}.jsonl") if f"{r['id']}.jsonl" in transcripts else None
                          r["trace_json"] = None            # where the original lives in a trace store is the original's
                      if by and t in WAS and r.get(WAS[t][0]) and r[WAS[t][0]] != by:
                          r[WAS[t][1]] = " ".join(str(r.get(WAS[t][1]) or said.get(str(r[WAS[t][0]])) or "").split())[:80] or None      # who the archive says: text, never a login
                      for col in USER_COLS.get(t, ()):
                          if not r.get(col):
                              continue
                          if by:                                         # restored by a login: everything in it is that login's now
                              r[col] = by
                          elif r[col] not in known:
                              r[col] = None
                              nulled += 1
                      if t in AUTO_ID:
                          r.pop("id", None)
                      r = {k: v for k, v in r.items() if k in cols}
                      ks = list(r)
                      verb = "INSERT OR IGNORE" if t in ("citations", "note_sources", "model_aliases", "doc_section_objects") else "INSERT"
                      c.execute(f"{verb} INTO {t}({','.join(ks)}) VALUES ({','.join('?' * len(ks))})", [(json.dumps(r[k]) if isinstance(r[k], (dict, list)) else r[k]) for k in ks])
        except (sqlite3.IntegrityError, sqlite3.InterfaceError, sqlite3.ProgrammingError, TypeError, KeyError):      # rows that do not fit the store: refused whole, nothing written
            raise ValueError("the archive does not fit together; it cannot be restored")
        for rel, n in files.items():
            dest = arch / rel
            if not dest.resolve().is_relative_to(arch.resolve()):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = z.read(n)
            if z.getinfo(n).file_size <= MAX_TABLE_BYTES:
                try:
                    data = _swap(data.decode("utf-8"), ids).encode("utf-8")
                except UnicodeDecodeError:
                    pass                                  # not text: written as it is
            dest.write_bytes(data)
    except (zipfile.BadZipFile, zlib_error, EOFError) as ex:
        raise ValueError("that zip file is damaged; it cannot be restored")
    counts = {k: len(v) for k, v in tables.items()}
    db.audit(workspace_id, "estate.restore", eid, {"file": Path(path).name, "counts": counts, "blobs": written, "authors_unknown": nulled, "held_others": bool(m.get("held_others"))}, by)
    return {"id": eid, "name": new_name or m["name"], "counts": counts, "blobs": written, "authors_unknown": nulled, "people": (m.get("people") or [])[:50],
            "exported_at": m.get("exported_at"), "active_snapshot": active, "share_locked": LOCKED if m.get("held_others") else None}
