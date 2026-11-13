"""Backup and restore of one estate, without credentials.

The archive is a zip: manifest.json; one JSON file per table slice that belongs
to the estate (register, snapshots with their files and parse runs, notes with
objects and sources, conversations with turns, the citations those turns and
notes own, finding state, proposals); the blobs the snapshots reference,
content-addressed, so a corrupt copy is caught on restore; and the .architect
folder's transcripts and reviews. Left out on purpose: users, password hashes,
sessions, invite codes, settings and the audit log. Author columns keep their
user ids; people.json carries id, name and role (no email) so a reader can tell
who was who, and a restore nulls the ids the target does not know.

Ids are kept, never remapped: citation ids are bound to snapshot ids and every
chip in every old answer must still open. So restore refuses an estate or
snapshot id the target already holds: delete the estate first, or restore on
another server.
"""
from __future__ import annotations
import hashlib, json, re, zipfile
from pathlib import Path
from .db import Db, now
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
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _safe_rel(name: str, prefix: str) -> str | None:
    """An archive entry under prefix as a relative path that stays inside the folder it is written to; None when it would
    not (a '..' segment, an absolute path, a drive letter). Zip entry names are text anyone could have typed, not paths."""
    rel = name[len(prefix):].replace("\\", "/")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in parts[0] or any(p in ("", ".", "..") for p in parts):
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
    t["estates"] = db.q("SELECT * FROM estates WHERE id=?", eid)
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
    """The manifest plus what a reader wants before restoring: model names, people, whether every blob is present."""
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ValueError("that is not a zip file")
    with z:
        names = set(z.namelist())
        if "manifest.json" not in names:
            raise ValueError("not an architect backup: no manifest.json")
        # sizes as the archive declares them, before anything is unzipped: a small file can claim to open into gigabytes
        infos = z.infolist()
        if sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES or any(i.file_size > MAX_TABLE_BYTES for i in infos if not i.filename.startswith("blobs/")):
            raise ValueError("the archive is too large once opened; it cannot be restored")
        m = json.loads(z.read("manifest.json"))
        if m.get("kind") != KIND:
            raise ValueError("not an architect estate backup")
        if int(m.get("format") or 0) > FORMAT:
            raise ValueError(f"backup format {m.get('format')} is newer than this server reads ({FORMAT})")
        if not _SAFE_ID.match(str(m.get("estate_id") or "")):
            raise ValueError("the archive's estate id is not a plain id; it cannot be restored")
        bad = [n for n in sorted(names) if n.startswith("architect/") and not n.endswith("/") and _safe_rel(n, "architect/") is None]
        if bad:
            raise ValueError(f"the archive holds a path that would leave its folder ({bad[0][:80]!r}); it cannot be restored")
        blobs_listed = json.loads(z.read("tables/blobs.json")) if "tables/blobs.json" in names else []
        m["blobs_missing"] = [b["sha256"] for b in blobs_listed if f"blobs/{b['sha256']}" not in names]
        m["people"] = json.loads(z.read("people.json")) if "people.json" in names else []
        m["models"] = [x["name"] for x in (json.loads(z.read("tables/models.json")) if "tables/models.json" in names else [])]
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


def import_estate(db: Db, blobs: BlobStore, data_root: str | Path, path: str | Path, workspace_id: str, by: str | None = None, name: str | None = None) -> dict:
    """Restore an archive into this store under its original ids. Refuses an estate or snapshot id already held."""
    m = inspect_archive(path)
    eid = m["estate_id"]
    have = reg.get_estate(db, eid)
    if have:
        raise ValueError("a workspace with this backup's id is already in this store: delete it first if it is yours, or restore on another server")
    if m["blobs_missing"]:
        raise ValueError(f"the archive is missing {len(m['blobs_missing'])} of its export files; it cannot be restored")
    new_name = (name or "").strip() or None
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        tables = {t: (json.loads(z.read(f"tables/{t}.json")) if f"tables/{t}.json" in names else []) for t in TABLES}
        check_closed(tables, eid)
        for t in ("conversations", "notes", "models", "documents", "doc_sections"):      # an id already held here belongs to someone else's workspace
            for r in tables[t]:
                if db.one(f"SELECT 1 FROM {t} WHERE id=?", r.get("id")):
                    raise ValueError(f"a {t.rstrip('s').replace('_', ' ')} id in the archive is already in this store; ids are kept on restore, so this archive cannot be restored here")
        for t in PATH_IDS:
            for r in tables[t]:
                if not _SAFE_ID.match(str(r.get("id") or "")):
                    raise ValueError(f"a {t[:-1]} id in the archive is not a plain id ({str(r.get('id'))[:60]!r}); it cannot be restored")
        for s in tables["snapshots"]:
            if db.one("SELECT 1 FROM snapshots WHERE id=?", s["id"]):
                raise ValueError(f"snapshot {s['id']} is already in this store; ids are kept on restore, so this archive cannot be restored here")
        written = 0
        for b in tables["blobs"]:
            data = z.read(f"blobs/{b['sha256']}")
            if hashlib.sha256(data).hexdigest() != b["sha256"]:
                raise ValueError(f"export file {b['sha256'][:12]} in the archive does not match its hash: the archive is damaged")
            blobs.put(data)
            written += 1
        arch = Path(data_root) / "estates" / eid / ".architect"
        transcripts = {n[len("architect/transcripts/"):] for n in names if n.startswith("architect/transcripts/")}
        known = {r["id"] for r in db.q("SELECT id FROM users")}
        nulled = 0
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
                        if new_name:
                            r["name"] = new_name
                    if t == "snapshots" and r.get("status") == "processing":
                        r["status"] = "draft"
                    if t == "parse_runs" and r.get("status") == "running":
                        r["status"] = "cancelled"
                    if t == "conversations":
                        r["transcript_path"] = str(arch / "transcripts" / f"{r['id']}.jsonl") if f"{r['id']}.jsonl" in transcripts else None
                    for col in USER_COLS.get(t, ()):
                        if r.get(col) and r[col] not in known:
                            r[col] = None
                            nulled += 1
                    if t in AUTO_ID:
                        r.pop("id", None)
                    r = {k: v for k, v in r.items() if k in cols}
                    ks = list(r)
                    verb = "INSERT OR IGNORE" if t in ("citations", "note_sources", "model_aliases", "doc_section_objects") else "INSERT"
                    c.execute(f"{verb} INTO {t}({','.join(ks)}) VALUES ({','.join('?' * len(ks))})", [r[k] for k in ks])
        for n in names:
            if n.startswith("architect/") and not n.endswith("/"):
                rel = _safe_rel(n, "architect/")
                if rel is None:
                    continue                                       # refused by inspect_archive already; belt and braces
                dest = arch / rel
                if not dest.resolve().is_relative_to(arch.resolve()):
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
    counts = {k: len(v) for k, v in tables.items()}
    db.audit(workspace_id, "estate.restore", eid, {"file": Path(path).name, "counts": counts, "blobs": written, "authors_unknown": nulled}, by)
    return {"id": eid, "name": new_name or m["name"], "counts": counts, "blobs": written, "authors_unknown": nulled, "people": m.get("people") or [],
            "exported_at": m.get("exported_at"), "active_snapshot": m.get("active_snapshot")}
