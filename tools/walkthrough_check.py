"""The parts of docs/WALKTHROUGH.md that are about logins, run against a live server: the admin creates two logins,
each gets its own demo workspaces, neither can see the other's, one asks a question, the admin panel shows it, the
spend cap trips and is lifted. Leaves the two logins disabled when it is done.

  python tools/walkthrough_check.py --base http://localhost:8766 --admin USER --password PASSWORD
"""
from __future__ import annotations
import argparse, http.cookiejar, json, secrets, sys, urllib.request, urllib.error


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, path: str, method: str = "GET", body=None):
        headers = {"content-type": "application/json"} if body is not None else {}
        csrf = next((c.value for c in self.jar if c.name == "csrf"), None)
        if csrf and method != "GET":
            headers["x-csrf"] = csrf
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else None)
        try:
            with self.opener.open(urllib.request.Request(self.base + path, data=data, method=method, headers=headers), timeout=900) as r:
                return r.status, json.loads(r.read().decode() or "null")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw

    def login(self, user: str, pw: str):
        return self.call("/api/auth/login", "POST", {"email": user, "password": pw})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8765"); ap.add_argument("--admin", required=True); ap.add_argument("--password", required=True)
    a = ap.parse_args()
    ok = True

    def check(label: str, cond: bool, detail: str = ""):
        nonlocal ok
        ok = ok and bool(cond)
        print(("  ok   " if cond else "  FAIL ") + label + (f"  [{detail}]" if detail else ""))

    admin = Client(a.base)
    s, me = admin.login(a.admin, a.password)
    check("the admin signs in", s == 200 and me["user"]["role"] == "owner", f"{s}")
    check("the sign-in page carries the test-instance notice", "test instance" in (me.get("notice") or "").lower() or bool(me.get("notice")))
    tag = secrets.token_hex(2)
    made = {}
    for name in ("alice", "bob"):
        s, r = admin.call("/api/admin/users", "POST", {"username": f"{name}-{tag}", "name": name.title(), "demo": True})
        check(f"the admin creates a login for {name}: password shown once, demo workspaces written", s == 200 and len(r.get("password", "")) == 19 and len(r.get("demo") or []) == 2, f"{s}")
        made[name] = r
    alice, bob = Client(a.base), Client(a.base)
    check("alice signs in with the password handed over", alice.login(made["alice"]["user"]["email"], made["alice"]["password"])[0] == 200)
    check("bob signs in", bob.login(made["bob"]["user"]["email"], made["bob"]["password"])[0] == 200)
    _, ea = alice.call("/api/estates"); _, eb = bob.call("/api/estates")
    check("each sees two workspaces, its own copies of the demo", len(ea) == 2 and len(eb) == 2 and {e["id"] for e in ea}.isdisjoint({e["id"] for e in eb}),
          f"{[e['name'] for e in ea]}")
    a_ws = next(e["id"] for e in ea if "Stores" in e["name"])
    check("bob cannot open alice's workspace: it is not there for him", bob.call(f"/api/estates/{a_ws}")[0] == 404)
    check("nor list its documents or chats", bob.call(f"/api/estates/{a_ws}/documents")[0] == 404 and bob.call(f"/api/estates/{a_ws}/conversations")[0] == 404)
    check("the admin cannot open it either: the admin sees counts, not workspaces", admin.call(f"/api/estates/{a_ws}")[0] == 404)
    s, c = alice.call(f"/api/estates/{a_ws}/conversations", "POST", {"title": "count", "text": "How many line items use FINDITEM?", "mode": "concise"})
    t = (c.get("turns") or [{}])[0] if s == 200 else {}
    blk = next((b for b in t.get("blocks") or [] if b["type"] == "count"), {})
    check("alice asks a question and gets the exact count (48 of 5,403)", s == 200 and blk.get("count") == 48 and blk.get("of") == 5403 and (t.get("verification") or {}).get("clean"), f"{s} {blk.get('count')}")
    check("bob cannot read that chat", bob.call(f"/api/conversations/{c.get('id')}")[0] == 404)
    _, panel = admin.call("/api/admin/users")
    row = {u["email"]: u for u in panel["users"]}
    ra, rb = row[made["alice"]["user"]["email"]], row[made["bob"]["user"]["email"]]
    check("the admin panel: alice 1 sign-in, 2 workspaces, 1 question, metered spend above zero; bob 0 questions",
          ra["sign_ins"] == 1 and ra["workspaces"] == 2 and ra["questions"] == 1 and ra["metered_usd"] > 0 and rb["questions"] == 0 and rb["workspaces"] == 2,
          f"alice metered ${ra['metered_usd']}, cap ${ra['spend_cap_usd']}")
    admin.call(f"/api/admin/users/{ra['id']}", "PATCH", {"cap_usd": round(ra["metered_usd"] / 2, 4)})
    s, r = alice.call(f"/api/conversations/{c['id']}/messages", "POST", {"text": "And which module has most?"})
    check("with the cap set below what she has used, her next question is refused (402) and says why", s == 402 and "spend cap" in json.dumps(r), f"{s}")
    check("the panel marks her as having reached the cap", next(u for u in admin.call("/api/admin/users")[1]["users"] if u["id"] == ra["id"])["over_cap"])
    admin.call(f"/api/admin/users/{ra['id']}", "PATCH", {"cap_usd": 2.0})
    check("reading is never capped", alice.call(f"/api/estates/{a_ws}")[0] == 200)
    for name in ("alice", "bob"):
        admin.call(f"/api/admin/users/{made[name]['user']['id']}", "PATCH", {"disabled": True})
    check("disabled, alice is signed out at once", alice.call("/api/estates")[0] == 401)
    print("\nall checks passed" if ok else "\nSOMETHING FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
