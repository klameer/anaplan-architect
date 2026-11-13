"""anaplan-architect: the gated tier over an estate of exports.

  anaplan-architect material ROOT --out material.md           what the reviewer reads
  anaplan-architect review ROOT --prompt prompt.md            write the prompt for any model
  anaplan-architect review ROOT --response answer.json ...    ingest a response (validated)
  anaplan-architect review ROOT --run ...                     Anthropic key from --api-key or ANTHROPIC_API_KEY
  anaplan-architect ask ROOT "question"                       one question, tools, citations
  anaplan-architect chat ROOT                                 a conversation
  anaplan-architect status ROOT [--set PATTERN STATUS REASON] statuses and memories

ROOT is the folder of model folders (Line Items + Actions per model); the
workspace lives in ROOT/.architect unless --workspace says otherwise.
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
from .store import Workspace
from . import material as matmod, opinion as opmod
from . import envfile
envfile.load()
from .review import render_review


def _kv(items):
    out = {}
    for s in items or []:
        k, _, v = s.partition("=")
        if k and v:
            out[k.strip()] = v.strip()
    return out


def _open(args) -> Workspace:
    return Workspace.open(args.root, args.workspace, aliases=_kv(args.alias), names=_kv(args.name), skip=args.skip)


def _write(path, text):
    Path(path).write_text(text, encoding="utf-8"); print(f"wrote {path}", file=sys.stderr)


def cmd_material(args):
    w = _open(args); _write(args.out, matmod.estate_material(w))


def cmd_review(args):
    w = _open(args)
    mat = matmod.estate_material(w)
    if args.prompt:
        _write(args.prompt, opmod.prompt(mat)); return
    op = None
    if args.response:
        op = opmod.ingest(w, Path(args.response).read_text(encoding="utf-8"), provider=args.provider or "ingested")
    elif args.run:
        key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            sys.exit("set ANTHROPIC_API_KEY or pass --api-key; or use --prompt then --response")
        op = opmod.run(w, mat, key, model_id=args.llm, critique=not args.no_critique)
    md = render_review(w, op, title=args.title or "", signed_by=args.signed_by or "")
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    if op:
        _write(w.root / "reviews" / f"{stamp}-opinion.json", json.dumps(op.to_dict(), indent=1, ensure_ascii=False))
    _write(args.out or (w.root / "reviews" / f"{stamp}-review.md"), md)
    if args.html:
        from anaplan_estate.htmlout import md_to_html
        css = Path(args.theme).read_text(encoding="utf-8") if args.theme else None
        logo = Path(args.logo).read_text(encoding="utf-8") if args.logo else None
        _write(args.html, md_to_html(md, args.title or "Architect's review", css=css, logo_svg=logo, brand=args.brand))


def _session(args, w):
    from .chat import Session
    from .provider import resolve, client_kw
    b = resolve(args.api_key, None if args.llm == "claude-sonnet-5" else args.llm)
    if b["provider"] == "none":
        sys.exit("no model backend: " + b["reason"])
    return Session(w, model_id=b["model"], **client_kw(b))


def cmd_ask(args):
    w = _open(args); s = _session(args, w)
    print(s.ask(args.question))


def cmd_chat(args):
    w = _open(args); s = _session(args, w)
    print(f"Architect ready over {len(w.estate.models)} model(s). Empty line to quit. Transcript: {s.path}")
    while True:
        try:
            q = input("\nyou> ").strip()
        except EOFError:
            break
        if not q:
            break
        print("\n" + s.ask(q))


def cmd_status(args):
    w = _open(args)
    if args.set:
        pid, st, reason = args.set
        print(json.dumps(w.set_status(pid, st, reason), indent=1))
    if args.remember:
        scope, text = args.remember
        print(json.dumps(w.remember(scope, text), indent=1))
    print(json.dumps({"statuses": w.statuses, "memories": w.memories}, indent=1, ensure_ascii=False))


def cmd_serve(args):
    from .web import serve
    serve(args.data, port=args.port, host=args.host, api_key=args.api_key, model_id=args.llm)


def cmd_demo(args):
    """Write the demo workspaces into a data folder (replacing any earlier copy of them). Needs no model key."""
    import os
    os.environ.setdefault("ARCHITECT_INLINE_PARSE", "1")
    from .web import create_app
    app = create_app(args.data)
    r = app.state.demo_reset(None)
    for w in r["workspaces"]:
        print(f"{w['name']}: {w['models']} model(s), {w['documents']} document(s)  [{w['id']}]")
    print(f"{len(r['questions'])} scripted questions: python tools/demo.py run")


def _store(args):
    from .orac.db import Db
    from .orac.blobs import BlobStore
    from .orac import estates as reg
    data = Path(args.data)
    db = Db(data / "orac.db")
    return data, db, BlobStore(data / "blobs", db), reg.default_workspace(db)


def cmd_backup(args):
    """One zip per estate: everything it owns, no credentials. `backup --list` names the estates."""
    from .orac import backup as bk, estates as reg
    data, db, blobs, ws = _store(args)
    ests = reg.list_estates(db, ws, include_archived=True)
    if args.list or not (args.estate or args.all):
        for e in ests:
            print(f"{e['id']}  {e['name']}{'  (archived)' if e['archived'] else ''}")
        if not ests:
            print("(no estates)")
        return
    picked = ests if args.all else [e for e in ests if e["id"] == args.estate or e["name"] == args.estate]
    if not picked:
        sys.exit(f"no estate {args.estate!r}")
    out = Path(args.out or ".")
    for e in picked:
        into_dir = len(picked) > 1 or out.is_dir() or not out.suffix
        dest = out / f"{e['name'].replace(' ', '_')}-{e['id']}.architect.zip" if into_dir else out
        print(f"wrote {bk.export_estate(db, blobs, data, e['id'], dest)}")


def cmd_restore(args):
    """Restore a backup under its original ids. Refuses an estate already in the store; `--inspect` only reads the manifest."""
    from .orac import backup as bk
    data, db, blobs, ws = _store(args)
    try:
        m = bk.inspect_archive(args.file)
        if args.inspect:
            print(json.dumps(m, indent=1, ensure_ascii=False))
            return
        r = bk.import_estate(db, blobs, data, args.file, ws, name=args.name)
    except ValueError as ex:
        sys.exit(str(ex))
    print(json.dumps(r, indent=1, ensure_ascii=False))


def _password(args) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    import getpass
    pw = getpass.getpass("Password (ten characters or more): ")
    if getpass.getpass("Again: ") != pw:
        sys.exit("passwords differ")
    return pw


def cmd_users(args):
    """Accounts are made here, on the server, never from the web."""
    from .orac.db import Db
    from .orac import auth, estates as reg
    db = Db(Path(args.data) / "orac.db")
    ws = reg.default_workspace(db)
    try:
        if args.action == "create":
            if not args.email:
                sys.exit("--email is required")
            pw = _password(args)
            if args.owner:
                u = auth.create_owner(db, ws, args.email, args.name or "", pw, args.workspace or "")
            else:
                u = auth.create_user(db, ws, args.email, args.name or "", pw, role="member")
            print(json.dumps(u, indent=1))
        elif args.action == "list":
            for u in auth.accounts(db, ws):
                print(f"{u['role']:7} {u['email']:40} {u['name']:24} joined {u['created'][:10]} last seen {(u['last_seen'] or '-')[:16]}{'  DISABLED' if u['disabled'] else ''}")
            if auth.no_accounts(db):
                print("(no accounts)")
        elif args.action in ("disable", "enable", "promote"):
            row = db.one("SELECT id FROM users WHERE email=?", (args.email or "").strip().lower())
            if not row:
                sys.exit(f"no account {args.email!r}")
            kw = {"disabled": args.action == "disable"} if args.action != "promote" else {"role": "owner"}
            print(json.dumps(auth.update_account(db, row["id"], by=None, **kw), indent=1))
        elif args.action == "password":
            row = db.one("SELECT * FROM users WHERE email=?", (args.email or "").strip().lower())
            if not row:
                sys.exit(f"no account {args.email!r}")
            pw = _password(args)
            auth._check(row["email"], pw, row["name"])
            h, salt = auth.hash_password(pw)
            db.run("UPDATE users SET pw_hash=?, pw_salt=? WHERE id=?", h, salt, row["id"])
            db.run("DELETE FROM sessions WHERE user_id=?", row["id"])
            print("password reset; every session of that account signed out")
    except (ValueError, PermissionError) as ex:
        sys.exit(str(ex))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="anaplan-architect", description="The architect's review and conversation over an estate of Anaplan exports.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("root"); sp.add_argument("--workspace")
        sp.add_argument("--alias", action="append"); sp.add_argument("--name", action="append"); sp.add_argument("--skip", action="append")
        sp.add_argument("--api-key"); sp.add_argument("--llm", default="claude-sonnet-5")

    s = sub.add_parser("material"); common(s); s.add_argument("--out", required=True); s.set_defaults(fn=cmd_material)
    s = sub.add_parser("review"); common(s)
    s.add_argument("--prompt"); s.add_argument("--response"); s.add_argument("--run", action="store_true"); s.add_argument("--no-critique", action="store_true")
    s.add_argument("--provider"); s.add_argument("--out"); s.add_argument("--html"); s.add_argument("--theme"); s.add_argument("--logo"); s.add_argument("--brand")
    s.add_argument("--title"); s.add_argument("--signed-by"); s.set_defaults(fn=cmd_review)
    s = sub.add_parser("ask"); common(s); s.add_argument("question"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("chat"); common(s); s.set_defaults(fn=cmd_chat)
    s = sub.add_parser("status"); common(s)
    s.add_argument("--set", nargs=3, metavar=("PATTERN", "STATUS", "REASON")); s.add_argument("--remember", nargs=2, metavar=("SCOPE", "TEXT")); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("serve", help="chat with your estate in a browser: upload exports, ask the architect")
    s.add_argument("--data", default="./data"); s.add_argument("--port", type=int, default=8765); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--api-key"); s.add_argument("--llm", default="claude-sonnet-5"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("demo", help="write the two fictional demo workspaces (Caldergate) into a data folder, the same every time")
    s.add_argument("--data", required=True); s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("users", help="accounts for the web app: created here on the server, never from the web")
    s.add_argument("action", choices=["create", "list", "disable", "enable", "promote", "password"])
    s.add_argument("--data", default="./data"); s.add_argument("--email"); s.add_argument("--name"); s.add_argument("--workspace")
    s.add_argument("--owner", action="store_true", help="create: make this the owner (only while no account exists)")
    s.add_argument("--password-stdin", action="store_true", help="read the password from stdin instead of prompting")
    s.set_defaults(fn=cmd_users)
    s = sub.add_parser("backup", help="one zip per estate: register, snapshots and exports, notes, conversations, decisions; no credentials")
    s.add_argument("--data", default="./data"); s.add_argument("--estate", help="estate id or name"); s.add_argument("--all", action="store_true")
    s.add_argument("--out", help="a .zip path for one estate, or a folder"); s.add_argument("--list", action="store_true"); s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("restore", help="restore an estate backup under its original ids (refuses one already in the store)")
    s.add_argument("file"); s.add_argument("--data", default="./data"); s.add_argument("--name", help="restore under another name")
    s.add_argument("--inspect", action="store_true", help="show the manifest and stop"); s.set_defaults(fn=cmd_restore)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
