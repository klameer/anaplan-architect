"""The launch capture set: every feature as stills and the moments that need motion as short clips, from the seeded
Caldergate demo workspaces, with a manifest. One command regenerates all of it.

  .venv/Scripts/python tools/captures.py --user admin --password ... [--base http://localhost:8768]
        [--prepare]        first write the demo afresh, make two demo logins and ask the scripted questions (about ten minutes of model time)
        [--only stills|clips]   [--docs]   also copy the stills the README and docs use into docs/img/ (tracked, small)

  out/captures/stills/<feature>-<shot>-desktop.png     1600 x 1000
  out/captures/stills/<feature>-<shot>-4x5.png         1080 x 1350, framed so a 4:5 crop loses nothing
  out/captures/clips/<moment>.mp4                      1280 x 720, H.264 (High, yuv420p, faststart), no audio (needs ffmpeg on the path)
  out/captures/clips/<moment>.webm                     the same clip as VP9; each file is played in the browser before it is listed
  out/captures/manifest.json                           file, kind, feature, the question asked, viewport, and what was done

Run it against a store made for it (a login called admin, demo logins, nothing else): every frame is then free of
real names. Capture mode (`?capture=1`) hides the signed-in name and the provider line as well. Only the two demo
workspaces are opened; no password, key or local path is on any page it visits. The waiting states are staged by
holding a request in the browser. The clips that ask a question or upload a document are real: the model answers.

It drives the Edge or Chrome already on the machine through Playwright (pip install playwright).
"""
from __future__ import annotations
import argparse, json, pathlib, shutil, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
OUT = ROOT / "out" / "captures"
FRAMES = {"desktop": (1600, 1000, 1.0), "4x5": (864, 1080, 1.25)}        # logical width, height, scale: 1600x1000 and 1080x1350
CLIP = (1280, 720)
PLAN_Q = "Give me a plan to build a lookup module that replaces the account mapping inside Forecast Opex."
LIVE_Q = "Why is CAL05 Opex OLD still in the model?"
DEMO_LOGINS = (("alex", "Alex"), ("sam", "Sam"))
README_GIFS = ("ask-a-question", "open-a-citation", "walk-a-reach", "show-diagram")          # clips the README shows moving
# the stills the README and the docs pages use: (still name without the size, file name under docs/img)
DOCS = {"hero": "why-answer-desktop", "why": "why-passage-desktop", "plan": "plan-steps-desktop", "plan-build": "plan-build-desktop", "overview": "overview-map-desktop",
        "improve": "improve-cards-desktop", "implications": "implications-rings-desktop", "count": "count-answer-desktop", "concise": "concise-diagram-desktop",
        "context": "context-view-desktop", "run": "run-timeline-desktop", "documents": "documents-cards-desktop", "dashboard": "dashboard-top-desktop",
        "model-map": "dashboard-model-map-desktop", "switcher": "workspace-switcher-desktop", "admin": "admin-panel-desktop", "tracing": "tracing-setting-desktop",
        "sign-in": "sign-in-page-desktop", "bert": "bert-thinking-desktop", "not-recorded": "not-recorded-answer-desktop"}


# The screencast's frames are JPEGs, which are full-range colour. Carried into the video as they are, Chrome refuses to decode
# it (the first frame shows, then PIPELINE_ERROR_DECODE), so every encode converts to limited range and says so in the file.
RANGE = "scale={w}:{h}:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p"
COLOUR = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
ENCODES = {".mp4": ["-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "slow", "-crf", "23", "-g", "50", "-movflags", "+faststart"],
           ".webm": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "33", "-row-mt", "1", "-g", "50"]}
PLAYS = """async () => { const v = document.querySelector('video');
  try { await v.play() } catch (e) { return { t: 0, err: String(e) } }
  await new Promise(r => setTimeout(r, 2500));
  return { t: v.currentTime, err: v.error && v.error.message, frames: v.getVideoPlaybackQuality().totalVideoFrames } }"""


def plays(browser, folder: pathlib.Path, names: list[str]) -> dict[str, str]:
    """Load each file in a video element in the real browser, press play, and see the time move. name -> '' or what went wrong."""
    import functools, http.server, threading
    quiet = type("Quiet", (http.server.SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(quiet, directory=str(folder)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out, page = {}, browser.new_page()
    try:
        for name in names:
            page.set_content(f"<video muted playsinline src='http://127.0.0.1:{srv.server_address[1]}/{name}'></video>")
            r = page.evaluate(PLAYS)
            out[name] = "" if r["t"] >= 1.0 and not r["err"] and r["frames"] > 10 else f"did not play in the browser (time {r['t']:.2f}s, {r['err'] or 'no error'})"
    finally:
        page.close(); srv.shutdown()
    return out


# run in the page: remove what this tool itself adds to the demo workspace (a held upload's file name, the live question's chat)
TIDY = """async ([eid, q]) => { const h = { 'x-csrf': (document.cookie.match(/csrf=([^;]+)/) || [])[1] };
  for (const d of (await (await fetch('/api/estates/' + eid + '/documents')).json()).documents)
    if (d.filename === 'Steering meeting notes 2024.md' || d.filename === 'CR-044 (second copy).md') await fetch('/api/documents/' + d.id, { method: 'DELETE', headers: h });
  for (const c of await (await fetch('/api/estates/' + eid + '/conversations')).json())
    if (c.title === q) await fetch('/api/conversations/' + c.id, { method: 'DELETE', headers: h }) }"""


def prepare(base: str, user: str, password: str) -> None:
    """The state every capture is taken from: the demo written afresh, two demo logins, the scripted questions asked."""
    import demo as d
    d.call(base, "/api/auth/login", "POST", {"email": user, "password": password})
    me = d.call(base, "/api/auth/me")
    if (me.get("trace") or {}).get("available"):          # the capture run's own questions are not sent to an outside tracer
        d.call(base, "/api/prefs", "PUT", {"trace_level": "off"})
    for w in d.call(base, "/api/demo/reset", "POST")["workspaces"]:
        print(f"demo: {w['name']} ({w['models']} models, {w['documents']} documents)")
    have = {u["email"] for u in d.call(base, "/api/admin/users")["users"]}
    for name, shown in DEMO_LOGINS:
        if name not in have:
            d.call(base, "/api/admin/users", "POST", {"username": name, "name": shown, "demo": True})
            print("demo login:", name)
    d.run(base, [])
    ws = next(w["id"] for w in d.call(base, "/api/demo")["workspaces"] if w["key"] == "caldergate-demo")
    d.ask(base, ws, PLAN_Q, "full", brief=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8768"); ap.add_argument("--user", default="admin"); ap.add_argument("--password", required=True)
    ap.add_argument("--prepare", action="store_true"); ap.add_argument("--only", choices=["stills", "clips"]); ap.add_argument("--docs", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.prepare:
        prepare(a.base, a.user, a.password)
    from playwright.sync_api import sync_playwright
    stills, clips = OUT / "stills", OUT / "clips"
    if a.only != "clips":
        shutil.rmtree(stills, ignore_errors=True)
    if a.only != "stills":
        shutil.rmtree(clips, ignore_errors=True)
    stills.mkdir(parents=True, exist_ok=True); clips.mkdir(parents=True, exist_ok=True)
    old = json.loads((OUT / "manifest.json").read_text(encoding="utf-8")) if (OUT / "manifest.json").exists() else []
    manifest: list[dict] = [m for m in old if a.only and m["kind"] != a.only.rstrip("s")]
    missed: list[str] = []

    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True); break
            except Exception:
                continue
        if browser is None:
            print("no Edge or Chrome found for Playwright to drive"); return 2

        def context(w, h, scale=1.0, video=None):
            kw = dict(viewport={"width": w, "height": h}, device_scale_factor=scale, reduced_motion="reduce", color_scheme="dark")
            if video:
                kw |= dict(record_video_dir=str(video), record_video_size={"width": w, "height": h})
            return browser.new_context(**kw)

        def sign_in(ctx):
            page = ctx.new_page()
            page.goto(a.base + "/app/?capture=1", wait_until="networkidle")
            if page.locator(".ds-auth").count():
                page.fill("#u", a.user); page.fill("#p", a.password); page.click(".ds-auth .go")
            page.wait_for_selector(".ds-side", timeout=20000); page.wait_for_timeout(1000)
            return page

        # ---- what is there to capture: the two demo workspaces and the answers already in them ----
        ctx = context(1600, 1000); page = sign_in(ctx)
        api = lambda p: page.evaluate("async p => (await fetch(p)).json()", p)
        demo = {w["key"]: w["id"] for w in api("/api/demo")["workspaces"]}
        cg, st = demo["caldergate-demo"], demo["caldergate-stores-demo"]
        page.evaluate(TIDY, [cg, LIVE_Q])          # what a run that stopped half way may have left
        chats: dict[str, dict] = {}
        for eid in (cg, st):
            for c in sorted(api(f"/api/estates/{eid}/conversations"), key=lambda c: c.get("updated") or c["created"]):
                turn = (api(f"/api/conversations/{c['id']}")["turns"] or [{}])[0]
                chats[(c["title"], turn.get("mode") or "full")] = {"eid": eid, "cid": c["id"], "q": turn.get("q") or c["title"]}
        ctx.close()

        def chat(starts: str, mode: str = "full"):
            return next((v for (title, m), v in chats.items() if title.startswith(starts) and m == mode), None)
        WHY, NOTREC = chat("Why is the account mapping"), chat("Why is the margin module")
        PLAN, PLANC = chat("Give me a plan to build a lookup module"), chat("Give me a plan to build a lookup module", "concise")
        SCEN, OVER, IMPROVE = chat("Give me a plan to build scenario planning"), chat("Give me an overview"), chat("How can we improve it")
        REACH, REACHC, COUNT = chat("What are the implications of changing SYS05"), chat("What are the implications of changing CAL03", "concise"), chat("How many line items use FINDITEM")

        def at(c):
            return f"e/{c['eid']}/chat/{c['cid']}" if c else None

        # each still: feature, shot, where, what to do before the frame, the question it shows
        S = lambda feature, shot, where, q=None, **do: {"feature": feature, "shot": shot, "where": where, "q": q, **do}
        Q = lambda c: c["q"] if c else None
        PLAN_OF = PLAN or SCEN
        shots = [
            S("why", "answer", at(WHY), Q(WHY)), S("why", "passage", at(WHY), Q(WHY), scroll=".ds-src"),
            S("not-recorded", "answer", at(NOTREC), Q(NOTREC)),
            S("plan", "build", at(PLAN_OF), Q(PLAN_OF), scroll=".ds-mod"), S("plan", "steps", at(PLAN_OF), Q(PLAN_OF), scroll=".ds-stepkey", note="the plan's numbered steps with the key to their colours"),
            S("plan", "uses", at(PLAN_OF), Q(PLAN_OF), scroll=".ds-uses"),
            S("overview", "map", at(OVER), Q(OVER), scroll=".ds-fig"), S("overview", "answer", at(OVER), Q(OVER)),
            S("improve", "cards", at(IMPROVE), Q(IMPROVE), scroll=".ds-card"), S("improve", "answer", at(IMPROVE), Q(IMPROVE)),
            S("implications", "rings", at(REACH), Q(REACH), scroll=".ds-fig"), S("implications", "steps", at(REACH), Q(REACH), click=".ds-fig .ds-seg button:nth-child(2)", scroll=".ds-fig"),
            S("implications", "answer", at(REACH), Q(REACH)),
            S("count", "answer", at(COUNT), Q(COUNT), note="one model of 5,403 line items"),
            S("concise", "plan", at(PLANC), Q(PLANC)),
            S("concise", "explain", at(PLANC), Q(PLANC), click=".ds-concise .st button.ds-aff:has-text('explain')", scroll=".ds-steplist", note="explain opened on a step"),
            S("concise", "diagram", at(PLANC), Q(PLANC), click=".ds-concise button.ds-aff:has-text('show diagram')", scroll=".ds-concise", note="show diagram opened"),
            S("concise", "reach", at(REACHC), Q(REACHC)), S("concise", "reach-diagram", at(REACHC), Q(REACHC), click="button.ds-aff:has-text('show diagram')", scroll=".ds-tiles", wait=".ds-turn .ds-fig svg"),
            S("context", "view", at(WHY), Q(WHY), click=".ds-foot button.ctx", scroll=".ds-ctxpanel"),
            S("run", "timeline", at(REACH), Q(REACH), click=".ds-foot button.ctx", scroll=".ds-run"),
            S("citation", "passage-open", at(WHY), Q(WHY), click=".ds-src .sh", wait=".evidence", note="a source card opened to its whole section"),
            S("documents", "cards", f"e/{cg}/documents"), S("documents", "sections", f"e/{cg}/documents", scroll=".ds-doc >> nth=0", note="a card with its sections and the objects it names"),
            S("documents", "upload", f"e/{cg}/documents", hold_upload=True, note="an upload being read (staged: the request is held)"),
            S("dashboard", "top", f"e/{cg}"), S("dashboard", "model-map", f"e/{cg}", scroll=".ds-fig"), S("dashboard", "inside-a-model", f"e/{cg}", scroll=".ds-dash.b"),
            S("workspace", "switcher", f"e/{cg}", click=".ds-ws > button"),
            S("admin", "panel", "admin"), S("admin", "workspaces", "admin", scroll=".ds-admin >> nth=1"),
            S("tracing", "setting", "settings", scroll="#trace-setting"), S("settings", "page", "settings"),
            S("bert", "thinking", at(WHY), "A question held back for the frame", thinking=True), S("bert", "question-failed", at(WHY), None, failing=True),
            S("bert", "not-found", f"e/{cg}/no-such-page"), S("bert", "empty-documents", f"e/{st}/documents"), S("bert", "workspace-ask", f"e/{cg}", scroll=".ds-askrow"),
        ]

        held: list = []          # requests the tool is holding back for a frame: answered by the tool afterwards, never let through to the server

        def release():
            for route, status, body in held:
                try:
                    route.fulfill(status=status, content_type="application/json", body=body)
                except Exception:
                    pass
            held.clear()

        def hold(page, pattern, status, body, now=False):
            def handler(route):
                if route.request.method != "POST":
                    route.continue_(); return
                if now:
                    route.fulfill(status=status, content_type="application/json", body=body)
                else:
                    held.append((route, status, body))
            page.route(pattern, handler)

        def settle(page, s):
            page.wait_for_selector(".ds-main", timeout=20000); page.wait_for_timeout(1400)
            if s.get("hold_upload"):
                hold(page, "**/api/estates/*/documents", 400, '{"detail":"held for the frame: nothing was uploaded"}')
                page.set_input_files(".ds-drop input[type=file]", {"name": "Steering meeting notes 2024.md", "mimeType": "text/markdown", "buffer": b"# notes"})
                page.wait_for_selector("[data-bert-place='document-upload']", timeout=5000)
            if s.get("thinking") or s.get("failing"):
                page.evaluate("document.querySelector('.ds.app')?.classList.add('asking')")          # the composer is needed to ask
                hold(page, "**/api/conversations/*/stream", 502, '{"detail":"the model call failed: the provider did not answer"}', now=bool(s.get("failing")))
                page.fill(".ds-compose textarea", "Why is the FX rate fixed at 1.27?"); page.keyboard.press("Enter")
                page.wait_for_selector("[data-bert-place='thinking']" if s.get("thinking") else "[data-bert-place='question-failed']", timeout=8000)
                page.evaluate("document.querySelector('.ds.app')?.classList.remove('asking')"); page.wait_for_timeout(300)
            if s.get("click"):
                page.locator(s["click"]).first.click(timeout=8000); page.wait_for_timeout(700)
            if s.get("wait"):
                page.wait_for_selector(s["wait"], timeout=15000); page.wait_for_timeout(500)
            if s.get("scroll"):
                page.locator(s["scroll"]).first.evaluate("el => { const m = document.querySelector('.ds-main'); m.scrollTop = el.getBoundingClientRect().top + m.scrollTop - 90 }")
                page.wait_for_timeout(500)
            elif s.get("thinking") or s.get("failing"):
                page.evaluate("() => { const m = document.querySelector('.ds-main'); m.scrollTop = m.scrollHeight }"); page.wait_for_timeout(300)
            else:
                page.evaluate("() => { const m = document.querySelector('.ds-main'); if (m) m.scrollTop = 0 }"); page.wait_for_timeout(300)          # a chat opens at its end: an answer is shown from its top

        if a.only != "clips":
            for frame, (w, h, scale) in FRAMES.items():
                ctx = context(w, h, scale); page = sign_in(ctx)
                for s in shots:
                    name = f"{s['feature']}-{s['shot']}-{frame}.png"
                    if not s["where"]:
                        missed.append(f"{name}: its question is not in the demo workspaces (run with --prepare)"); continue
                    try:
                        page.goto(f"{a.base}/app/?capture=1#/{s['where']}", wait_until="networkidle")
                        page.reload(wait_until="networkidle")          # each frame from a fresh page: nothing left open from the one before
                        settle(page, s)
                        page.screenshot(path=str(stills / name))
                        release(); page.wait_for_timeout(300)
                        page.unroute_all(behavior="ignoreErrors")
                        manifest.append({"file": f"stills/{name}", "kind": "still", "feature": s["feature"], "shot": s["shot"], "question": s["q"], "viewport": f"{round(w * scale)}x{round(h * scale)}",
                                         "framing": frame, "note": s.get("note", "")})
                    except Exception as e:
                        missed.append(f"{name}: {str(e).splitlines()[0][:140]}")
                        try:
                            release(); page.unroute_all(behavior="ignoreErrors")
                        except Exception:
                            pass
                ctx.close()
            # the sign-in page, signed out
            for frame, (w, h, scale) in FRAMES.items():
                ctx = context(w, h, scale); page = ctx.new_page()
                page.goto(a.base + "/app/?capture=1", wait_until="networkidle"); page.wait_for_timeout(800)
                if page.locator(".ds-auth").count():
                    name = f"sign-in-page-{frame}.png"; page.screenshot(path=str(stills / name))
                    manifest.append({"file": f"stills/{name}", "kind": "still", "feature": "sign-in", "shot": "page", "question": None, "viewport": f"{round(w * scale)}x{round(h * scale)}", "framing": frame, "note": ""})
                ctx.close()

        # ---- clips: one context each, recorded from the first frame to the last ----
        def clip(name, feature, question, steps, note=""):
            """One clip: the browser's own screencast (a frame whenever the page changes, with its time), encoded with the
            ffmpeg on this machine at 25 frames a second into an H.264 mp4 and a VP9 webm, both limited-range. No audio.
            Each file is then played in the browser; one whose time does not move is deleted and reported, not listed."""
            import base64, subprocess
            tmp = clips / ("_" + name); shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
            ctx = context(*CLIP)
            page = sign_in(ctx)
            frames: list = []
            cdp = ctx.new_cdp_session(page)

            def on_frame(ev):
                frames.append((ev["metadata"]["timestamp"], ev["data"]))
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            cdp.on("Page.screencastFrame", on_frame)
            cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": CLIP[0], "maxHeight": CLIP[1], "everyNthFrame": 1})
            try:
                steps(page)
                page.wait_for_timeout(1200)
            except Exception as e:
                missed.append(f"clips/{name}.webm: {str(e).splitlines()[0][:140]}")
            try:
                cdp.send("Page.stopScreencast")
            except Exception:
                pass
            ctx.close()
            if len(frames) < 2:
                missed.append(f"clips/{name}.webm: no frames were recorded"); shutil.rmtree(tmp, ignore_errors=True); return
            lines = []
            for i, (ts, data) in enumerate(frames):
                (tmp / f"f{i:05d}.jpg").write_bytes(base64.b64decode(data))
                lines += [f"file 'f{i:05d}.jpg'", f"duration {max((frames[i + 1][0] - ts) if i + 1 < len(frames) else 1.2, 0.02):.3f}"]
            lines.append(f"file 'f{len(frames) - 1:05d}.jpg'")
            (tmp / "list.txt").write_text(chr(10).join(lines), encoding="utf-8")
            secs, made = round(frames[-1][0] - frames[0][0] + 1.2, 1), []
            for ext, codec in ENCODES.items():
                r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-vf", "fps=25," + RANGE.format(w=CLIP[0], h=CLIP[1]),
                                    *codec, *COLOUR, "-an", str((clips / f"{name}{ext}").resolve())], cwd=tmp, capture_output=True, text=True)
                if r.returncode != 0:
                    missed.append(f"clips/{name}{ext}: ffmpeg: {r.stderr.strip()[:140]}")
                else:
                    made.append(f"{name}{ext}")
            shutil.rmtree(tmp, ignore_errors=True)
            for file, wrong in plays(browser, clips, made).items():
                if wrong:
                    missed.append(f"clips/{file}: {wrong}"); (clips / file).unlink(missing_ok=True); continue
                manifest.append({"file": f"clips/{file}", "kind": "clip", "feature": feature, "shot": name, "question": question, "viewport": f"{CLIP[0]}x{CLIP[1]}", "seconds": secs,
                                 "codec": "h264" if file.endswith(".mp4") else "vp9", "plays": True, "note": note})

        def open_(page, where, pause=1500):
            page.goto(f"{a.base}/app/?capture=1#/{where}", wait_until="networkidle"); page.wait_for_selector(".ds-main", timeout=20000); page.wait_for_timeout(pause)

        def scroll_to(page, sel, pause=900):
            page.locator(sel).first.evaluate("el => { const m = document.querySelector('.ds-main'); m.scrollTo({ top: el.getBoundingClientRect().top + m.scrollTop - 90, behavior: 'smooth' }) }"); page.wait_for_timeout(pause)

        if a.only != "stills":
            def ask(page):
                open_(page, f"e/{cg}/chat/new")
                page.evaluate("document.querySelector('.ds.app')?.classList.add('asking')")          # this clip is about asking: the composer shows, and the rest of capture mode holds
                box = page.locator(".ds-compose textarea").first
                box.click(); page.keyboard.type(LIVE_Q, delay=28); page.wait_for_timeout(600); page.keyboard.press("Enter")
                page.wait_for_selector(".ds-turn .ds-foot", timeout=170000); page.wait_for_timeout(1500)
                if page.locator(".ds-src").count():
                    scroll_to(page, ".ds-src", 1800)
                page.evaluate(TIDY, [cg, LIVE_Q])          # the demo is left as it was
            clip("ask-a-question", "why", LIVE_Q, ask, "a real question, answered by the model while recording; the composer is shown")

            def citation(page):
                open_(page, at(WHY)); scroll_to(page, ".ds-src", 1400)
                page.locator(".ds-src .sh").first.hover(); page.wait_for_timeout(1200); page.locator(".ds-src .sh").first.click()
                page.wait_for_selector(".evidence", timeout=10000); page.wait_for_timeout(2200)
                page.locator(".evidence").first.hover(); page.mouse.wheel(0, 260); page.wait_for_timeout(1800); page.mouse.wheel(0, -260); page.wait_for_timeout(1200)
                page.keyboard.press("Escape"); page.wait_for_timeout(1400)
            if WHY:
                clip("open-a-citation", "citation", Q(WHY), citation, "a source card opened to its passage in the drawer")

            def diagram(page):
                open_(page, at(PLANC)); page.wait_for_timeout(1200)
                b = page.locator(".ds-concise button.ds-aff:has-text('show diagram')").first
                b.hover(); page.wait_for_timeout(600); b.click(); page.wait_for_timeout(2200)
                e = page.locator(".ds-concise .st button.ds-aff:has-text('explain')").first
                e.scroll_into_view_if_needed(); e.hover(); page.wait_for_timeout(500); e.click(); page.wait_for_timeout(2000)
                x = page.locator("button.ds-aff:has-text('expand to Full')").first
                x.scroll_into_view_if_needed(); x.hover(); page.wait_for_timeout(500); x.click(); page.wait_for_timeout(1500)
                scroll_to(page, ".ds-mod", 2000)
            if PLANC:
                clip("show-diagram", "concise", Q(PLANC), diagram, "Concise: show diagram, explain on a step, expand to Full")

            def upload(page):
                open_(page, f"e/{cg}/documents")
                body = (ROOT / "examples" / "caldergate" / "documents" / "CR-044 Retire CAL05 Opex OLD.md").read_bytes()
                page.evaluate("""async eid => { const csrf = (document.cookie.match(/csrf=([^;]+)/) || [])[1]; for (const d of (await (await fetch('/api/estates/' + eid + '/documents')).json()).documents)
                    if (d.title.startsWith('CR-044 (second copy)')) await fetch('/api/documents/' + d.id, { method: 'DELETE', headers: { 'x-csrf': csrf } }) }""", cg)
                n = page.locator(".ds-doc").count()
                page.set_input_files(".ds-drop input[type=file]", {"name": "CR-044 (second copy).md", "mimeType": "text/markdown", "buffer": body.replace(b"# CR-044", b"# CR-044 (second copy)", 1)})
                for _ in range(300):
                    if page.locator(".ds-doc").count() > n:
                        break
                    page.wait_for_timeout(200)
                page.wait_for_timeout(800); page.locator(".ds-doc").last.scroll_into_view_if_needed(); page.wait_for_timeout(2500)
                page.once("dialog", lambda d: d.accept())
                page.locator(".ds-doc").last.locator("button:has-text('Remove')").click(); page.wait_for_timeout(1500)          # the demo is left as it was
            clip("document-upload", "documents", None, upload, "a document uploaded, read and shown as a card with its sections; then removed again")

            def switch(page):
                open_(page, f"e/{cg}"); page.wait_for_timeout(800)
                page.locator(".ds-ws > button").click(); page.wait_for_timeout(1400)
                row = page.locator(".ds-ws .pop a.row:has-text('Caldergate Stores')").first
                row.hover(); page.wait_for_timeout(700); row.click(); page.wait_for_timeout(3200)
                page.locator(".ds-ws > button").click(); page.wait_for_timeout(1000)
                page.locator(".ds-ws .pop a.row:has-text('Caldergate Distribution Group')").first.click(); page.wait_for_timeout(2600)
            clip("switch-workspace", "workspace", None, switch, "from one workspace to the other and back: the page, the counts and the chats all change")

            def rings(page):
                open_(page, at(REACH)); scroll_to(page, ".ds-fig", 1500)
                svg = page.locator(".ds-turn .ds-fig svg").first
                box = svg.bounding_box()
                if box:
                    cx, cy, r = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, min(box["width"], box["height"]) / 2
                    page.mouse.move(cx, cy); page.wait_for_timeout(900)
                    for k in range(1, 8):                    # outward, a ring at a time
                        page.mouse.move(cx + r * 0.9 * k / 7, cy - r * 0.25 * k / 7, steps=12); page.wait_for_timeout(750)
                page.locator(".ds-fig .ds-seg button:nth-child(2)").first.click(); page.wait_for_timeout(2600)
                page.locator(".ds-fig .ds-seg button:nth-child(1)").first.click(); page.wait_for_timeout(1400)
                scroll_to(page, ".ds-list", 1800)
            if REACH:
                clip("walk-a-reach", "implications", Q(REACH), rings, "the pointer moves out from the change a ring at a time, then the same reach as steps, then by module")
        browser.close()

    manifest.sort(key=lambda m: (m["kind"], m["file"]))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    n_still, n_clip = sum(m["kind"] == "still" for m in manifest), sum(m["kind"] == "clip" for m in manifest)
    print(f"{n_still} stills and {n_clip} clips in {OUT}  (manifest.json)")
    for x in missed:
        print("  not captured:", x)
    if a.docs:
        img = ROOT / "docs" / "img"; img.mkdir(parents=True, exist_ok=True)
        for name, still in DOCS.items():
            src = stills / f"{still}.png"
            if src.exists():
                shutil.copyfile(src, img / f"{name}.png")
            else:
                print("  docs/img: no still for", name)
        # the clips the README plays, as GIFs (a README cannot play a video file from the repository), and the two brand marks it shows
        import subprocess
        for name in README_GIFS:
            src = clips / f"{name}.webm"
            if not src.exists():
                print("  docs/img: no clip for", name); continue
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf",
                                "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=220:stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                                str(img / f"{name}.gif")], capture_output=True, text=True)
            if r.returncode:
                print("  docs/img: ffmpeg:", r.stderr.strip()[:120])
        brand = ROOT / "web" / "src" / "design" / "brand"
        shutil.copyfile(brand / "logo.svg", img / "logo.svg"); shutil.copyfile(brand / "bert-architect-hello.svg", img / "bert-hello.svg")
        files = [p for p in img.iterdir() if p.is_file()]
        print(f"docs/img: {len(files)} files, {sum(p.stat().st_size for p in files) // 1024} KB")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
