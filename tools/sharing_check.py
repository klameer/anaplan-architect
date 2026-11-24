"""Workspace sharing, seen in a real browser: two team-mates, one shared workspace, and the stills of it.

  .venv/Scripts/python tools/sharing_check.py --password <the capture store's admin> [--base http://localhost:8768] [--ask]

Runs against the capture store (demo logins only, Caldergate only). The admin puts the two demo logins in one team;
the first makes a workspace from the demo exports, Shared; the second opens it, sees who can see it, and (with --ask)
asks in the first one's chat. It checks what each page says, takes the stills into out/captures/stills/sharing-*.png
(both framings, listed in the manifest), then makes the workspace private, checks the second login has lost it, and
deletes it: the capture store is left as it was, except that the two demo logins are now in a team.

Passwords are never printed: the two demo logins get a new one each for this run, held in memory only.
"""
from __future__ import annotations
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "caldergate"
OUT = ROOT / "out" / "captures"
TEAM, NAME = "Caldergate Finance", "Group planning FY27"
QUESTION = "Why is the account mapping written into the Forecast Opex formula instead of a lookup table?"
FRAMES = {"desktop": (1600, 1000, 1.0), "4x5": (864, 1080, 1.25)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8768"); ap.add_argument("--user", default="admin"); ap.add_argument("--password", required=True)
    ap.add_argument("--ask", action="store_true", help="also ask one question as each login (two model calls)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    import httpx
    from playwright.sync_api import sync_playwright
    checks: list[tuple[bool, str]] = []
    check = lambda what, ok: (checks.append((bool(ok), what)), print(("  ok   " if ok else "  FAIL ") + what))[0]

    def client(user, pw):
        c = httpx.Client(base_url=a.base, timeout=600)
        r = c.post("/api/auth/login", json={"email": user, "password": pw}); r.raise_for_status()
        c.headers["x-csrf"] = c.cookies.get("csrf") or ""
        return c
    admin = client(a.user, a.password)
    if (admin.get("/api/auth/me").json().get("trace") or {}).get("available"):
        admin.put("/api/prefs", json={"trace_level": "off"})
    users = {u["email"]: u for u in admin.get("/api/admin/users").json()["users"]}
    people = {}
    for login in ("alex", "sam"):
        if login not in users:
            print(f"the capture store has no login called {login}: run tools/captures.py --prepare first"); return 2
        admin.post("/api/admin/teams", json={"name": TEAM})                # made once; refused, harmlessly, when it is there already
        r = admin.patch(f"/api/admin/users/{users[login]['id']}", json={"team": TEAM, "reset_password": True}).json()
        people[login] = (client(login, r["password"]), r["password"], r["user"]["name"])
        people[login][0].put("/api/prefs", json={"trace_level": "off"}) if False else None
    alex, sam = people["alex"][0], people["sam"][0]
    for c in (alex, sam):                                # tidy what a run that stopped half way left
        for e in c.get("/api/estates").json():
            if e["name"] == NAME and e.get("mine"):
                c.request("DELETE", f"/api/estates/{e['id']}", json={"confirm": NAME})
    check("the admin put both demo logins in one team", {u["email"]: u.get("team") for u in admin.get("/api/admin/users").json()["users"] if u["email"] in ("alex", "sam")} == {"alex": TEAM, "sam": TEAM})

    # alex makes a workspace from the demo exports, Shared
    man = json.loads((EX / "demo.json").read_text(encoding="utf-8"))["workspaces"][0]
    files, names = [], []
    for m in man["models"]:
        folder = EX / m["folder"]
        files.append(("line_items", ("Line Items.csv", (folder / "Line Items.csv").read_bytes(), "text/csv")))
        for kind, fname in (("actions", "Actions.csv"), ("modules", "Modules.csv")):
            p = folder / fname
            files.append((kind, (fname if p.exists() else "", p.read_bytes() if p.exists() else b"", "text/csv")))
        names.append(m["name"])
    r = alex.post("/api/estates", data={"name": NAME, "model_names": names, "visibility": "shared"}, files=files)
    r.raise_for_status(); eid = r.json()["id"]
    doc = EX / man["documents"][0]["file"]
    alex.post(f"/api/estates/{eid}/documents", files=[("files", (doc.name, doc.read_bytes(), "text/markdown"))]).raise_for_status()
    check("a team-mate lists it as shared, with the team and who made it", any(e["id"] == eid and e["visibility"] == "shared" and e["team"] == TEAM and not e["mine"] for e in sam.get("/api/estates").json()))
    check("the admin does not: counts, never content", admin.get(f"/api/estates/{eid}").status_code == 404)
    cid = None
    if a.ask:
        cid = alex.post(f"/api/estates/{eid}/conversations", json={"title": QUESTION, "text": QUESTION}).json()["id"]
        sam.post(f"/api/conversations/{cid}/messages", json={"text": "What would it take to move it to a lookup now?"}).raise_for_status()
        turns = alex.get(f"/api/conversations/{cid}").json()["turns"]
        check("the chat says who asked each question", [t["by_name"] for t in turns] == [people["alex"][2], people["sam"][2]])
    else:
        cid = alex.post(f"/api/estates/{eid}/conversations", json={"title": "A chat in a shared workspace"}).json()["id"]

    stills = OUT / "stills"; stills.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = [m for m in (json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []) if m.get("feature") != "sharing"]
    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True); break
            except Exception:
                continue
        if browser is None:
            print("no Edge or Chrome found for Playwright to drive"); return 2

        def page_for(login, w, h, scale):
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, reduced_motion="reduce", color_scheme="dark")
            page = ctx.new_page()
            page.goto(a.base + "/app/?capture=1", wait_until="networkidle")
            page.fill("#u", login); page.fill("#p", a.password if login == a.user else people[login][1]); page.click(".ds-auth .go")
            page.wait_for_selector(".ds-side", timeout=20000); page.wait_for_timeout(800)
            return ctx, page

        def shot(page, name, frame, w, h, scale, note):
            f = f"sharing-{name}-{frame}.png"
            page.screenshot(path=str(stills / f))
            manifest.append({"file": f"stills/{f}", "kind": "still", "feature": "sharing", "shot": name, "question": None, "viewport": f"{round(w * scale)}x{round(h * scale)}", "framing": frame, "note": note})

        def go(page, where, wait=".ds-main"):
            page.goto(f"{a.base}/app/?capture=1#/{where}", wait_until="networkidle"); page.reload(wait_until="networkidle")
            page.wait_for_selector(wait, timeout=20000); page.wait_for_timeout(1200)

        for frame, (w, h, scale) in FRAMES.items():
            first = frame == "desktop"
            # the maker
            ctx, page = page_for("alex", w, h, scale)
            go(page, "new", "#access-choice")
            if first:
                check("new workspace: Private and Shared, one line under each, Private chosen", page.locator(".ds-access-choice button").count() == 2 and page.locator(".ds-access-choice button.on").inner_text().startswith("Private")
                      and f"Everyone in {TEAM} can open it" in page.locator(".ds-access-choice").inner_text())
            page.locator("#access-choice").scroll_into_view_if_needed(); page.wait_for_timeout(300)
            shot(page, "new-workspace-choice", frame, w, h, scale, "Private or Shared with your team, chosen when the workspace is made")
            go(page, f"e/{eid}", "[data-access-strip]")
            if first:
                txt = " ".join(page.locator("[data-access-strip]").inner_text().split())
                check("the maker's workspace page says who can open it and offers Make private", f"Everyone in {TEAM} can open it" in txt and "Made by you" in txt and "Make private" in txt)
            shot(page, "workspace-shared", frame, w, h, scale, "a shared workspace: who can open it, and the maker's way to change that")
            page.locator("[data-access-strip] button").first.click(); page.wait_for_selector(".ds-modal", timeout=5000); page.wait_for_timeout(300)
            if first:
                check("the dialog names who loses access before anything happens", people["sam"][2] in page.locator(".ds-modal").inner_text() and "lose it at once" in page.locator(".ds-modal").inner_text())
            shot(page, "make-private-dialog", frame, w, h, scale, "making a shared workspace private: who loses access")
            page.keyboard.press("Escape"); page.wait_for_timeout(200)
            page.locator(".ds-ws > button").click(); page.wait_for_selector(".ds-ws .pop", timeout=5000); page.wait_for_timeout(300)
            if first:
                check("the switcher marks the shared workspace and the private ones", f"shared with {TEAM}" in page.locator(".ds-ws .pop").inner_text() and "· private" in page.locator(".ds-ws .pop").inner_text())
            shot(page, "switcher", frame, w, h, scale, "the workspace switcher: which are private, which are shared and with which team")
            ctx.close()
            # the team-mate
            ctx, page = page_for("sam", w, h, scale)
            go(page, f"e/{eid}", "[data-access-strip]")
            if first:
                txt = " ".join(page.locator("[data-access-strip]").inner_text().split())
                check("a team-mate sees who made it and that only the maker or the admin can change it", f"Made by {people['alex'][2]}" in txt and "or the admin can change this" in txt and "Make private" not in txt)
            go(page, f"e/{eid}/chat/{cid}", ".ds-main")
            page.evaluate("document.querySelector('.ds.app')?.classList.add('asking')"); page.wait_for_timeout(300)      # capture mode hides the chat box: this frame is about it
            if first:
                check("above the chat box: everyone in the team can read this", f"Everyone in {TEAM} can read and add to the chats" in page.locator("[data-access-note]").inner_text())
                if a.ask:
                    check("each answer says who asked", page.locator("[data-asked-by]").count() == 2)
            page.evaluate("() => { const m = document.querySelector('.ds-main'); if (m) m.scrollTop = m.scrollHeight }"); page.wait_for_timeout(400)
            shot(page, "chat-shared", frame, w, h, scale, "a chat in a shared workspace: who asked, and who can read what you type")
            ctx.close()
            # the admin
            ctx, page = page_for(a.user, w, h, scale)
            go(page, "admin", ".ds-admin")
            if first:
                check("the admin panel has a Team column and says which workspaces are shared", page.locator(f"td[data-team='{TEAM}']").count() == 2 and page.locator("td[data-ws-access='shared']").count() >= 1)
            shot(page, "admin-teams", frame, w, h, scale, "the admin panel: each login's team, and which workspaces are shared")
            ctx.close()
        browser.close()

    # private again: the team-mate is out at once; then the workspace goes, and the store is as it was
    alex.patch(f"/api/estates/{eid}", json={"visibility": "private"}).raise_for_status()
    check("made private: the team-mate has lost it at once", sam.get(f"/api/estates/{eid}").status_code == 404 and alex.get(f"/api/estates/{eid}").status_code == 200)
    check("the workspace made for this run is deleted", alex.request("DELETE", f"/api/estates/{eid}", json={"confirm": NAME}).status_code == 200)
    manifest.sort(key=lambda m: (m["kind"], m["file"]))
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    bad = [w for ok, w in checks if not ok]
    print(f"\n{len(checks) - len(bad)} of {len(checks)} checks passed; {len([m for m in manifest if m.get('feature') == 'sharing'])} stills in {stills}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
