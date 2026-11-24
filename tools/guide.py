"""Make the getting-started guide from the app as it is now. One command; rerun it whenever a screen changes.

  .venv/Scripts/python tools/guide.py --password <the capture store's admin> [--base http://localhost:8768] [--ask]

Reads src/anaplan_architect/guide/spec.json (the words, the screens, what each callout points at, by selector) and,
against the capture store (Caldergate only, the demo login alex):

  - takes each screen at 1280 x 800;
  - looks each callout's element up on the page and records where it is, so the arrow points at the thing itself;
  - writes src/anaplan_architect/static/guide/guide.json and img/*.png   what the app shows at #/guide
  - writes docs/onboarding/getting-started.html                           the same guide as one file: images inlined,
                                                                          no script, no outside request

A callout whose element is not on the page stops the run and says which: the guide is never written with an arrow
pointing at nothing. --ask asks the three questions the screens need (why, the CR-031 plan, the reach of a change)
when alex's demo workspace does not have them yet: three model calls.
"""
from __future__ import annotations
import argparse, datetime, json, pathlib, shutil, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT_STATIC = ROOT / "src" / "anaplan_architect" / "static" / "guide"
OUT_HTML = ROOT / "docs" / "onboarding" / "getting-started.html"
BRAND = ROOT / "web" / "src" / "design" / "brand"
W, H = 1280, 800
TEAM, SHARED = "Caldergate Finance", "Group planning FY27"
CHATS = {"why": "Why is the account mapping written into the Forecast Opex formula", "plan": "Build what change request CR-031 asks for", "implications": "What are the implications of changing SYS05 FX Rates"}
# where a number sits relative to what it points at: (which edge of the element the arrow lands on, how far away the number is)
SIDES = {"left": ((0.0, 0.5), (-78, -34)), "right": ((1.0, 0.5), (78, -34)), "top": ((0.22, 0.0), (-34, -64)), "bottom": ((0.22, 1.0), (-34, 64))}
FLIP = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
R = 20          # room a number needs around its centre, in pixels


def place(box: dict, side: str, taken: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """(x, y) on the element's edge and (tx, ty) for the number, inside the screen and clear of the numbers already placed."""
    def at(sd):
        (fx, fy), (dx, dy) = SIDES[sd]
        x = min(max(box["x"] + box["width"] * fx, 6), W - 6); y = min(max(box["y"] + box["height"] * fy, 6), H - 6)
        tx = min(max(x + dx, R + 4), W - R - 4); ty = min(max(y + dy, R + 4), H - R - 4)
        return x, y, tx, ty
    x, y, tx, ty = at(side)
    if ((tx - x) ** 2 + (ty - y) ** 2) ** 0.5 < 44:          # pushed back onto its own target by the edge of the screen: come from the other side
        x, y, tx, ty = at(FLIP[side])
    for _ in range(8):
        if all(((tx - ox) ** 2 + (ty - oy) ** 2) ** 0.5 > 2.4 * R for ox, oy in taken):
            break
        ty = min(max(ty + (2.6 * R if ty < H / 2 else -2.6 * R), R + 4), H - R - 4)
    return x, y, tx, ty


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8768"); ap.add_argument("--user", default="admin"); ap.add_argument("--password", required=True)
    ap.add_argument("--ask", action="store_true", help="ask the three questions the screens need, when they are not there yet")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    import httpx
    from playwright.sync_api import sync_playwright
    from anaplan_architect import guide as guidemod
    spec = guidemod.spec()

    def client(user, pw):
        c = httpx.Client(base_url=a.base, timeout=900)
        c.post("/api/auth/login", json={"email": user, "password": pw}).raise_for_status()
        c.headers["x-csrf"] = c.cookies.get("csrf") or ""
        return c
    admin = client(a.user, a.password)
    users = {u["email"]: u for u in admin.get("/api/admin/users").json()["users"]}
    if "alex" not in users:
        print("the capture store has no login called alex: run tools/captures.py --prepare first"); return 2
    admin.post("/api/admin/teams", json={"name": TEAM})                # made once; refused, harmlessly, when it is there already
    r = admin.patch(f"/api/admin/users/{users['alex']['id']}", json={"team": TEAM, "reset_password": True}).json()
    alex_pw = r["password"]                                   # held in memory for this run, never printed
    alex = client("alex", alex_pw)
    if (alex.get("/api/auth/me").json().get("trace") or {}).get("available"):
        alex.put("/api/prefs", json={"trace_level": "off"})
    alex.put("/api/prefs", json={"guide_seen": True, "answer_mode": "full"})
    mine = alex.get("/api/estates").json()
    demo = next((e["id"] for e in mine if e["name"] == "Caldergate Distribution Group"), None)
    if demo is None:
        print("alex has no Caldergate demo workspace: run tools/captures.py --prepare first"); return 2
    for e in mine:                                            # what a run that stopped half way left
        if e["name"] == SHARED and e.get("mine"):
            alex.request("DELETE", f"/api/estates/{e['id']}", json={"confirm": SHARED})
    shared = alex.post("/api/estates/create", json={"name": SHARED, "visibility": "shared"}).json()["id"]

    def chat_for(key):
        """The newest chat for a question whose answer has everything the screen points at."""
        for c in alex.get(f"/api/estates/{demo}/conversations").json():
            if c["title"].startswith(CHATS[key]) and c["turns"]:
                t = alex.get(f"/api/conversations/{c['id']}").json()["turns"][0]
                if any(b["type"] == "followups" for b in t.get("blocks") or []):
                    return c["id"]
        return None
    showcase = {q["key"]: q["text"] for q in json.loads((ROOT / "examples" / "caldergate" / "demo.json").read_text(encoding="utf-8"))["showcase"]}
    chats = {}
    for key in CHATS:
        chats[key] = chat_for(key)
        if chats[key] is None:
            if not a.ask:
                print(f"alex's demo workspace has no up-to-date answer to the {key} question: run again with --ask"); return 2
            print(f"asking: {showcase[key][:70]}…")
            chats[key] = alex.post(f"/api/estates/{demo}/conversations", json={"title": showcase[key], "text": showcase[key], "mode": "full"}).json()["id"]

    img = OUT_STATIC / "img"
    tmp = OUT_STATIC / "_new"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    problems: list[str] = []
    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True); break
            except Exception:
                continue
        if browser is None:
            print("no Edge or Chrome found for Playwright to drive"); return 2
        ctx_kw = dict(viewport={"width": W, "height": H}, device_scale_factor=1, reduced_motion="reduce", color_scheme="dark")
        out_ctx = browser.new_context(**ctx_kw); out_page = out_ctx.new_page()
        in_ctx = browser.new_context(**ctx_kw); page = in_ctx.new_page()
        page.goto(a.base + "/app/?capture=1", wait_until="networkidle")
        page.fill("#u", "alex"); page.fill("#p", alex_pw); page.click(".ds-auth .go"); page.wait_for_selector(".ds-side", timeout=20000)

        for sec in spec["sections"]:
            for sc in sec.get("screens") or []:
                p = out_page if sc.get("as") == "signed-out" else page
                where = sc["where"].replace("{demo}", demo).replace("{shared}", shared)
                if where.startswith("chat:"):
                    where = f"e/{demo}/chat/{chats[where[5:]]}"
                p.goto(f"{a.base}/app/?capture=1#/{where}", wait_until="networkidle"); p.reload(wait_until="networkidle")
                p.wait_for_selector(".ds-auth" if sc.get("as") == "signed-out" else ".ds-main", timeout=20000); p.wait_for_timeout(1200)
                if sc.get("compose"):
                    p.evaluate("document.querySelector('.ds.app')?.classList.add('asking')")          # capture mode hides the chat box: this screen is about it
                if sc.get("click"):
                    p.locator(sc["click"]).first.click(timeout=8000); p.wait_for_timeout(600)
                if sc.get("wait"):
                    p.wait_for_selector(sc["wait"], timeout=15000); p.wait_for_timeout(400)
                if sc.get("scroll"):
                    p.locator(sc["scroll"]).first.evaluate("el => { const m = document.querySelector('.ds-main'); m.scrollTop = el.getBoundingClientRect().top + m.scrollTop - 150 }")
                elif sc.get("scroll_end"):
                    p.evaluate("() => { const m = document.querySelector('.ds-main'); m.scrollTop = m.scrollHeight }")
                elif sc.get("as") != "signed-out" and not sc.get("click"):
                    p.evaluate("() => { const m = document.querySelector('.ds-main'); if (m) m.scrollTop = 0 }")
                p.wait_for_timeout(600)
                taken: list[tuple[float, float]] = []
                calls = []
                for n, c in enumerate(sc["callouts"], 1):
                    box = None
                    for sel in [x.strip() for x in c["sel"].split(",")]:
                        loc = p.locator(sel)
                        for i in range(min(loc.count(), 6)):
                            b = loc.nth(i).bounding_box() if loc.nth(i).is_visible() else None
                            if b and b["width"] > 2 and b["height"] > 2 and b["y"] + b["height"] > 4 and b["y"] < H - 4 and b["x"] < W - 4:
                                box = b; break
                        if box:
                            break
                    if box is None:
                        problems.append(f"{sec['id']} / {sc['name']}: nothing on the screen matches {c['sel']!r}"); continue
                    box = {"x": max(box["x"], 0), "y": max(box["y"], 0), "width": min(box["width"], W - max(box["x"], 0)), "height": min(box["height"], H - max(box["y"], 0))}
                    x, y, tx, ty = place(box, c.get("side") or "left", taken)
                    taken.append((tx, ty))
                    calls.append({"n": n, "x": round(x / W, 4), "y": round(y / H, 4), "tx": round(tx / W, 4), "ty": round(ty / H, 4), "text": c["text"]})
                p.screenshot(path=str(tmp / f"{sc['name']}.png"))
                sc.update({"image": f"{sc['name']}.png", "width": W, "height": H, "callouts": calls})
                for k in ("as", "where", "click", "wait", "scroll", "scroll_end", "compose"):
                    sc.pop(k, None)
                print(f"  {sec['id']:<24} {sc['name']:<14} {len(calls)} callout{'s' if len(calls) != 1 else ''}")
        browser.close()
    alex.request("DELETE", f"/api/estates/{shared}", json={"confirm": SHARED})          # the capture store is left as it was
    if problems:
        shutil.rmtree(tmp, ignore_errors=True)
        print("\nnot written: a callout must point at something.\n  " + "\n  ".join(problems)); return 1

    shutil.rmtree(img, ignore_errors=True); tmp.rename(img)
    spec.pop("about", None)
    spec["captured"] = datetime.date.today().isoformat()
    (OUT_STATIC / "guide.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    images = {f.name: f.read_bytes() for f in img.glob("*.png")}
    berts = {f.stem.replace("bert-architect-", ""): f.read_bytes() for f in BRAND.glob("bert-architect-*.svg")}
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html = guidemod.to_html(spec, images, berts, guidemod.questions())
    OUT_HTML.write_text(html, encoding="utf-8", newline="\n")
    n_calls = sum(len(sc["callouts"]) for s in spec["sections"] for sc in s.get("screens") or [])
    print(f"\n{len(spec['sections'])} sections, {len(images)} screens, {n_calls} callouts\n  {OUT_STATIC / 'guide.json'}\n  {OUT_HTML}  ({len(html) // 1024} KB, one file)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
