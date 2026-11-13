"""Where Bert stands in the app, checked in a real browser, with a still of each place.

  .venv/Scripts/python tools/bert_check.py --user karim --password ... [--base http://localhost:8765]
                                           [--empty http://localhost:8767 --empty-user admin --empty-password ...]

The rule (Karim, 2026-11-13: "a fun idea but a serious tool"): Bert around the answers, never in them. This walks to
each place he should be, saves a capture of it under out/bert/, and then opens every answer in the demo workspaces and
checks nothing of him is inside an answer's text, figures, citations, diagrams, plan, context view, run timeline or
verdict. He is a still everywhere: the check also confirms nothing about him animates.

Only the seeded Caldergate demo workspaces are opened. The waiting and failed states are staged by holding or
answering the request in the browser, so no question is sent to a model. `--empty` is a store with one admin and
nothing else, for the empty states. Exit 1 if anything fails.
"""
from __future__ import annotations
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# everything that is an answer, or the evidence and workings of one
INSIDE = (".md-lead, .ds-rest, .ds-fig, .ds-src, .ds-ctxpanel, .ds-foot, .ds-steplist, .ds-mod, .ds-tiles, .ds-uses, .ds-count, .ds-concise, .ds-list, .ds-card, "
          ".ds-quiet, .ds-flags, .evidence, .mermaid-box")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8765"); ap.add_argument("--user"); ap.add_argument("--password")
    ap.add_argument("--empty"); ap.add_argument("--empty-user", default="admin"); ap.add_argument("--empty-password")
    ap.add_argument("--shots", default=str(ROOT / "out" / "bert"))
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    shots = pathlib.Path(a.shots); shots.mkdir(parents=True, exist_ok=True)
    results: list[tuple[bool, str]] = []
    places: dict[str, str] = {}

    def check(label, cond, detail=""):
        results.append((bool(cond), label))
        print(("  ok   " if cond else "  FAIL ") + label + (f"  [{str(detail)[:200]}]" if detail and not cond else ""))

    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True); break
            except Exception:
                continue
        new = lambda: browser.new_context(viewport={"width": 1500, "height": 950}, reduced_motion="reduce", color_scheme="dark")

        def capture(page, place, name=None, pad=24):
            """A still of the place: Bert and the block he stands beside."""
            fig = page.locator(f"[data-bert-place='{place}']").first
            page.evaluate("() => document.querySelectorAll('#toast').forEach(t => { t.style.visibility = 'hidden' })")          # a message from an earlier staged step is not part of this place (hidden, not removed: the app owns the node)
            page.wait_for_timeout(250)
            seen = fig.evaluate("""el => { const r = el.getBoundingClientRect(), mid = [r.x + r.width / 2, r.y + r.height / 2]; const top = document.elementFromPoint(mid[0], mid[1]);
                return r.height > 0 && mid[1] > 0 && mid[1] < innerHeight && !!top && (el.contains(top) || top.contains(el)) }""")
            check(f"  {name or place}: in view, with nothing lying over him", seen)
            box = fig.evaluate("""el => { const host = el.closest('.ds-bert-note, .ds-none, .ds-askrow, .box, .ds-drop, .card') || el; const r = host.getBoundingClientRect(), own = host === el;
                return own ? { x: r.x, y: r.y - 70, width: 760, height: r.height + 110 } : { x: r.x, y: r.y, width: r.width, height: Math.min(r.height, 520) } }""")
            vp = page.viewport_size
            clip = {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad)}
            clip["width"] = min(vp["width"] - clip["x"], box["width"] + 2 * pad); clip["height"] = min(vp["height"] - clip["y"], box["height"] + 2 * pad)
            path = shots / f"{name or place}.png"
            page.screenshot(path=str(path), clip=clip)
            page.evaluate("() => document.querySelectorAll('#toast').forEach(t => { t.style.visibility = '' })")
            places[name or place] = str(path.relative_to(ROOT)).replace("\\", "/")

        def there(page, place, state, label, name=None):
            fig = page.locator(f"[data-bert-place='{place}']")
            ok = fig.count() == 1 and fig.first.get_attribute("data-bert") == state and fig.first.locator("img").count() == 1
            check(label, ok, f"{fig.count()} found")
            if ok:
                still = fig.first.locator("img").evaluate("el => { const c = getComputedStyle(el); return [c.animationName, c.transitionDuration, el.getAttribute('alt'), el.getAttribute('aria-hidden'), el.naturalWidth > 0] }")
                check(f"  {place}: a still (no animation, no transition), hidden from screen readers, and the image loaded", still[0] == "none" and still[1] in ("0s", "") and still[2] == "" and still[3] == "true" and still[4], still)
                capture(page, place, name)
            return ok

        def sign_in(ctx, base, user, password):
            page = ctx.new_page()
            page.goto(base + "/app/", wait_until="networkidle")
            if page.locator(".ds-auth").count():
                page.fill("#u", user or ""); page.fill("#p", password or ""); page.click(".ds-auth .go")
            page.wait_for_selector(".ds-side", timeout=20000); page.wait_for_timeout(1200)
            return page

        # ---- sign-in ----
        ctx = new(); page = ctx.new_page()
        page.goto(a.base + "/app/", wait_until="networkidle")
        if page.locator(".ds-auth").count():
            there(page, "sign-in", "hello", "sign-in: Bert says hello beside the wordmark")
            txt = page.locator(".ds-auth").inner_text()
            check("sign-in: /architect, your Anaplan build buddy; Anaplan Architect is not the product's name", "your Anaplan build buddy" in txt and "Anaplan Architect" not in txt and page.title() == "/architect: your Anaplan build buddy")
        ctx.close()

        ctx = new(); page = sign_in(ctx, a.base, a.user, a.password)
        api = lambda p: page.evaluate("async p => (await fetch(p)).json()", p)
        demo = {w["key"]: w["id"] for w in api("/api/demo")["workspaces"]}
        cg, st = demo["caldergate-demo"], demo["caldergate-stores-demo"]
        go = lambda path: (page.goto(f"{a.base}/app/#/{path}", wait_until="networkidle"), page.wait_for_timeout(1500))

        # ---- the workspace page: beside the ask box ----
        go(f"e/{cg}")
        if there(page, "workspace-ask", "neutral", "workspace: Bert beside the ask box"):
            where = page.evaluate("""() => { const b = document.querySelector("[data-bert-place='workspace-ask']"); return { inTitle: !!b.closest('h1, .ds-kick'), inFigures: !!b.closest('.ds-tiles, .ds-fig, .ds-sec') } }""")
            check("  workspace: not in the page's title and not among its figures", not where["inTitle"] and not where["inFigures"], where)

        # ---- documents: none yet (Caldergate Stores has no documents) ----
        go(f"e/{st}/documents")
        there(page, "empty-documents", "information", "documents: the empty state")
        # ---- reading an upload: the request is held in the browser so the waiting state can be seen ----
        go(f"e/{cg}/documents")
        hold = {"on": True}
        def slow_upload(route):
            if route.request.method == "POST" and hold["on"]:
                page.wait_for_timeout(1500)
                route.fulfill(status=400, content_type="application/json", body=json.dumps({"detail": "held by the check: nothing was uploaded"}))
            else:
                route.continue_()
        page.route("**/api/estates/*/documents", slow_upload)
        page.set_input_files(".ds-drop input[type=file]", {"name": "held.md", "mimeType": "text/markdown", "buffer": b"# held\n\nnot sent"})
        page.wait_for_selector("[data-bert-place='document-upload']", timeout=5000)
        there(page, "document-upload", "processing", "documents: Bert while an upload is being read")
        page.wait_for_timeout(1800); hold["on"] = False; page.unroute("**/api/estates/*/documents")

        # ---- the chat: thinking, then a question that got no answer, then the cap ----
        chats = api(f"/api/estates/{cg}/conversations")
        first = sorted(chats, key=lambda c: c["created"])[0]["id"]
        go(f"e/{cg}/chat/{first}")
        mode = {"kind": "error"}
        def staged(route):
            page.wait_for_timeout(1600)
            if mode["kind"] == "cap":
                route.fulfill(status=402, content_type="application/json", body=json.dumps({"detail": {"message": "This login has reached its spend cap: $2.01 used of $2.00. Ask the person who gave you the login to raise it."}}))
            else:
                route.fulfill(status=502, content_type="application/json", body=json.dumps({"detail": "the model call failed: the provider did not answer"}))
        page.route("**/api/conversations/*/stream", staged)
        page.fill(".ds-compose textarea", "A question the check holds back"); page.keyboard.press("Enter")
        page.wait_for_selector("[data-bert-place='thinking']", timeout=5000)
        if there(page, "thinking", "investigating", "chat: Bert while the answer is being worked on"):
            check("  thinking: his own line, from his spec", "Still investigating." in page.locator("[data-bert-place='thinking']").inner_text())
        page.wait_for_selector("[data-bert-place='question-failed']", timeout=8000)
        if there(page, "question-failed", "error", "chat: a question that got no answer"):
            note = page.locator(".ds-bert-note", has=page.locator("[data-bert-place='question-failed']")).inner_text()
            check("  failed: said plainly, and the question is back in the box", "did not get an answer" in note and "nothing was lost" in note and page.locator(".ds-compose textarea").input_value() == "A question the check holds back")
        mode["kind"] = "cap"
        page.keyboard.press("Enter") if False else page.locator(".ds-compose .send").click()
        page.wait_for_selector("[data-bert-place='cap-reached']", timeout=8000)
        if there(page, "cap-reached", "warning", "chat: the spend cap reached"):
            check("  cap: the amount and who to ask, in plain words", "spend cap" in page.locator(".ds-bert-note", has=page.locator("[data-bert-place='cap-reached']")).inner_text())
        page.unroute("**/api/conversations/*/stream")

        # ---- Not recorded: the frame of the answer ----
        nr = next((c["id"] for c in chats if c["title"].startswith("Why is the margin module")), None)
        if nr:
            go(f"e/{cg}/chat/{nr}")
            if there(page, "not-recorded", "question", "Not recorded: Bert on the frame of the answer"):
                where = page.evaluate(f"""() => {{ const b = document.querySelector("[data-bert-place='not-recorded']"); return {{ inFrame: !!b.closest('.ds-none'), inside: !!b.closest({json.dumps(INSIDE)}) }} }}""")
                check("  Not recorded: on the frame, outside the answer's own text and workings", where["inFrame"] and not where["inside"], where)

        # ---- an address that opens nothing ----
        go(f"e/{cg}/no-such-page")
        there(page, "not-found", "question", "404: a page the app does not have", "not-found-page")
        go("e/not-a-workspace-anywhere")
        there(page, "not-found", "question", "404: a workspace that is not here, or not this login's", "not-found-workspace")
        check("  404: said in place, with the way back, and nothing about whose it might be", "Nothing at this address" in page.locator(".ds-main").inner_text() and "Go to your workspaces" in page.locator(".ds-main").inner_text())

        # ---- the boundary: every answer in the two demo workspaces, opened; nothing of Bert inside one ----
        inside_any, opened = [], 0
        for eid in (cg, st):
            for c in api(f"/api/estates/{eid}/conversations"):
                go(f"e/{eid}/chat/{c['id']}")
                for aff in page.locator(".ds-turn button.ds-aff:has-text('show diagram'), .ds-turn button.ds-aff:has-text('expand to Full')").all()[:3]:
                    try:
                        aff.click(timeout=1500)
                    except Exception:
                        pass
                ctxb = page.locator(".ds-foot button.ctx").first
                if ctxb.count():
                    ctxb.click(); page.wait_for_timeout(300)
                n = page.evaluate(f"""() => [...document.querySelectorAll("[data-bert], img[src*='bert']")].filter(b => b.closest({json.dumps(INSIDE)})).map(b => b.getAttribute('data-bert-place') || b.getAttribute('src')).length""")
                opened += 1
                if n:
                    inside_any.append(c["title"][:50])
        check(f"the boundary: {opened} answers opened with their figures, sources, plans, context and run timeline; Bert is inside none of them", opened >= 5 and not inside_any, inside_any[:3])
        ctx.close()

        # ---- the empty states, on a store with one admin and nothing else ----
        if a.empty:
            ctx = new(); page = sign_in(ctx, a.empty, a.empty_user, a.empty_password)
            page.goto(a.empty + "/app/#/new", wait_until="networkidle"); page.wait_for_timeout(1200)
            there(page, "empty-workspaces", "information", "no workspaces yet: the empty state")
            page.goto(a.empty + "/app/#/admin", wait_until="networkidle"); page.wait_for_timeout(1500)
            there(page, "admin-no-logins", "information", "admin: no other logins yet")
            there(page, "admin-no-workspaces", "information", "admin: no workspaces on the instance yet")
            # parsing an upload: held in the browser, nothing is created
            page.goto(a.empty + "/app/#/new", wait_until="networkidle"); page.wait_for_timeout(1000)
            def held(route):
                if route.request.method == "POST":
                    page.wait_for_timeout(1600)
                    route.fulfill(status=400, content_type="application/json", body=json.dumps({"detail": "held by the check: nothing was created"}))
                else:
                    route.continue_()
            page.route("**/api/estates", held)
            li = (ROOT / "examples" / "caldergate" / "exports" / "1 Caldergate Data Hub" / "Line Items.csv").read_bytes()
            page.set_input_files("input[type=file] >> nth=0", {"name": "Caldergate Data Hub - Line Items.csv", "mimeType": "text/csv", "buffer": li})
            page.click("button:has-text('Parse and open')")
            page.wait_for_selector("[data-bert-place='upload']", timeout=5000)
            there(page, "upload", "processing", "new workspace: Bert while the exports are parsed")
            page.wait_for_timeout(1900); page.unroute("**/api/estates")
            ctx.close()
        browser.close()

    # the stills themselves: nothing in them can move
    brand = ROOT / "web" / "src" / "design" / "brand"
    moving = [p.name for p in brand.glob("bert-*.svg") if any(w in p.read_text(encoding="utf-8") for w in ("<animate", "@keyframes", "<script", "<style"))]
    check("the stills hold no animation, script or style", not moving, moving)
    (shots / "places.json").write_text(json.dumps(places, indent=1), encoding="utf-8")
    bad = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(bad)} of {len(results)} checks passed" + (": " + "; ".join(r[1] for r in bad) if bad else ""))
    print("captures:"); [print(f"  {k}: {v}") for k, v in places.items()]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
