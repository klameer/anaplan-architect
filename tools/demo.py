"""Drive the running app from the command line (default http://localhost:8765). Needs nothing installed.

  python tools/demo.py reset                      write the two demo workspaces afresh (the same state every time)
  python tools/demo.py run [--only KEY ...]       ask the scripted questions, print a verdict table, write out/demo-run.json
  python tools/demo.py ask "question" [--mode concise] [--estate ID]

`run` exits 1 unless every answer's verdict is clean. docs/WALKTHROUGH.md uses all three.
"""
from __future__ import annotations
import argparse, http.cookiejar, json, pathlib, sys, time, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = "caldergate-demo"


JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR))


def call(base: str, path: str, method: str = "GET", body=None, timeout: int = 900):
    headers, data = {}, None
    csrf = next((c.value for c in JAR if c.name == "csrf"), None)
    if csrf and method != "GET":
        headers["x-csrf"] = csrf
    if body is not None:
        data = json.dumps(body).encode(); headers["content-type"] = "application/json"
    elif method != "GET":
        data = b""
    for attempt in range(90):
        try:
            with OPENER.open(urllib.request.Request(base + path, data=data, method=method, headers=headers), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 409 and "reparsing" in detail and attempt < 89:      # the exports are being re-read: ask again in a moment
                time.sleep(2); continue
            raise SystemExit(f"{method} {path} -> {e.code}: {detail[:400]}")


def show(t: dict, question: str, cid: str, brief: bool = False) -> None:
    v = t["verification"] or {}
    print(f"\n== {question}\n   kind {t['kind']} · mode {t['mode']} · conversation {cid}\n")
    print(t["a"] if not brief else t["a"][:700] + (" …" if len(t["a"]) > 700 else ""))
    print("\n-- verdict:", "clean" if v.get("clean") else "FLAGGED", {k: v.get(k) for k in ("cited", "unchecked", "unverified", "phantom", "quotes", "why")},
          "untraced:", (v.get("figures") or {}).get("untraced"))
    print("-- blocks:", [b["type"] for b in t["blocks"]])
    for b in t["blocks"]:
        if b["type"] == "passages":
            for p in b["items"]:
                for q in p["quotes"]:
                    print(f"   [{'found' if q['found'] else 'NOT FOUND'}] {p['document']} · {p['heading']}: \"{q['quote'][:150]}\"")
        if b["type"] == "build_plan":
            for m in b["plan"]["modules"]:
                print(f"   step {m['step']}: {m['name']} ({m['state']}, {len(m['items'])} line items)")
            for ch in b["plan"].get("changes") or []:
                print(f"   change: {ch['module']}.{ch['name']}: {ch['old_formula'][:70]} -> {ch['formula'][:90]}")
            u = b["plan"].get("uses") or {}
            print("   uses:", len(u.get("modules") or []), "modules,", len(u.get("line_items") or []), "line items,", len(u.get("lists") or []), "lists")
            for st in b["plan"].get("steps") or []:
                print(f"   {st['n']:>2}. [{st['kind']}] {st['text'][:150]}")
            print("   checks:", b["plan"]["checks"])
        if b["type"] == "count":
            print(f"   count {b['count']} of {b['of']} · by model {b['by_model']}")
        if b["type"] == "reach":
            print(f"   reach of {b['ref']}: {b['counts']['line_items']} line items, {b['counts']['modules']} modules, up to {b['counts']['max_distance']} steps")
    ctx = t["context"]
    print(f"-- context: {ctx['total']} of {ctx['budget']} tokens; left out {sum(i['tokens'] for i in ctx['left_out'])}")
    if not brief:
        for i in ctx["items"]:
            print(f"   {i['tokens']:>6}  {i['kind']:<12} {i['label'][:70]}  ({i['why'][:70]})")
        for i in ctx["left_out"]:
            print(f"   {i['tokens']:>6}  left out     {i['label'][:70]}")
    print("-- run:", " > ".join(s["name"] for s in t["run"]["steps"]), f"· {t['run']['seconds']} s")


def ask(base: str, eid: str, question: str, mode: str, brief: bool = False) -> tuple[dict, str]:
    c = call(base, f"/api/estates/{eid}/conversations", "POST", {"title": question, "text": question, "mode": mode})
    t = c["turns"][0]
    show(t, question, c["id"], brief)
    return t, c["id"]


def run(base: str, only: list[str]) -> int:
    info = call(base, "/api/demo")
    if not info["available"]:
        raise SystemExit("the demo files are not installed with this server")
    if not all(w["present"] for w in info["workspaces"]):
        raise SystemExit("the demo workspaces are not there: python tools/demo.py reset")
    rows, record = [], {}
    for q in info["questions"]:
        if only and q["key"] not in only:
            continue
        ws = next((w["id"] for w in info["workspaces"] if w.get("key") == q["workspace"]), q["workspace"])    # this login's copy of the demo workspace
        t, cid = ask(base, ws, q["text"], q.get("mode", "full"), brief=True)
        v = t["verification"] or {}
        record[q["key"]] = {"conversation": cid, "workspace": ws, "turn": t.get("id"), "kind": t["kind"], "mode": t["mode"], "clean": bool(v.get("clean")), "question": q["text"],
                            "context": t["context"]["total"], "budget": t["context"]["budget"], "seconds": t["run"]["seconds"], "tools": [s["name"] for s in t["run"]["steps"] if s["kind"] == "tool"],
                            "blocks": [b["type"] for b in t["blocks"]], "moment": q.get("moment")}
        rows.append((q["key"], t["kind"], t["mode"], "clean" if v.get("clean") else "FLAGGED", t["context"]["total"], t["run"]["seconds"]))
    out = ROOT / "out" / "demo-run.json"
    out.parent.mkdir(exist_ok=True)
    prev = json.loads(out.read_text(encoding="utf-8")) if out.exists() and only else {}
    out.write_text(json.dumps({**prev, **record}, indent=1), encoding="utf-8")
    print("\n" + "=" * 78)
    print(f"{'question':<22}{'kind':<14}{'mode':<9}{'verdict':<9}{'context':>9}{'seconds':>9}")
    for r in rows:
        print(f"{r[0]:<22}{r[1]:<14}{r[2]:<9}{r[3]:<9}{r[4]:>9}{r[5]:>9}")
    bad = [r[0] for r in rows if r[3] != "clean"]
    print("=" * 78 + f"\n{len(rows) - len(bad)} of {len(rows)} clean" + (f"; flagged: {', '.join(bad)}" if bad else "") + f" · written to {out.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["reset", "run", "ask"])
    ap.add_argument("question", nargs="?")
    ap.add_argument("--estate", default=DEMO)
    ap.add_argument("--mode", default="full")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--base", default="http://localhost:8765")
    ap.add_argument("--user", help="sign in first (a server with logins)"); ap.add_argument("--password")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.user:
        call(a.base, "/api/auth/login", "POST", {"email": a.user, "password": a.password or ""})
    if a.cmd == "reset":
        r = call(a.base, "/api/demo/reset", "POST")
        for w in r["workspaces"]:
            print(f"{w['name']}: {w['models']} model(s), {w['documents']} document(s)  [{w['id']}]")
    elif a.cmd == "run":
        sys.exit(run(a.base, a.only))
    else:
        ask(a.base, a.estate, a.question, a.mode)
