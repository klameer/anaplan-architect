"""Capture the showcase moments (the ten in the v0.2 plan) from the running app as clean stills: 16:9 (1920x1080) and 4:5
(1080x1350), no login name, no provider line, the app's own colours. One screen, one question each.

  python tools/demo.py reset && python tools/demo.py run       the demo state and its answers (writes out/demo-run.json)
  .venv/Scripts/python tools/capture.py [--only 1 4 ...]       writes out/moments/<n>-<name>-16x9.png and -4x5.png

It drives a real browser through Playwright, using the Edge or Chrome already on the machine (nothing is downloaded):
  pip install playwright
Nothing in the app animates, so a frame taken once the page has settled is the frame. A clip of a moment is this
script's steps recorded: the same clicks in the same order.
"""
from __future__ import annotations
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRAMES = {"16x9": (1600, 900, 1.2), "4x5": (800, 1000, 1.35)}          # logical width, height, scale -> 1920x1080 and 1080x1350


def moments(run: dict) -> list[dict]:
    """What to open and what to do for each moment. `chat` names a scripted question; `page` a page of a demo workspace."""
    def chat(key):
        r = run.get(key)
        return (r["workspace"], f"chat/{r['conversation']}") if r else None
    cg = (run.get("why") or {}).get("workspace", "caldergate-demo")
    return [
        {"n": 1, "name": "why-quoted-passage", "at": chat("why"), "shots": [{"tag": "answer"}, {"tag": "passage", "scroll": ".ds-src"}]},
        {"n": 2, "name": "clean-context", "at": chat("why"), "shots": [{"tag": "context", "click": ".ds-foot button.ctx", "scroll": ".ds-ctxpanel"}]},
        {"n": 3, "name": "build-plan", "at": chat("plan"), "shots": [{"tag": "full", "scroll": ".ds-tiles"}, {"tag": "steps", "scroll": ".ds-mod"}]},
        {"n": 3, "name": "build-plan-concise", "at": chat("plan-concise"), "shots": [{"tag": "concise"}]},
        {"n": 4, "name": "reach-of-a-change", "at": chat("implications"), "shots": [{"tag": "rings", "scroll": ".ds-fig"}, {"tag": "steps", "click": ".ds-fig .ds-seg button:nth-child(2)", "scroll": ".ds-fig"}]},
        {"n": 5, "name": "exact-count", "at": chat("count"), "shots": [{"tag": "count"}]},
        {"n": 6, "name": "improve", "at": chat("improve"), "shots": [{"tag": "plan", "scroll": ".ds-fig"}]},
        {"n": 7, "name": "run-timeline", "at": chat("implications"), "shots": [{"tag": "run", "click": ".ds-foot button.ctx", "scroll": ".ds-run"}]},
        {"n": 8, "name": "documents", "at": (cg, "documents"), "shots": [{"tag": "cards"}]},
        {"n": 8, "name": "workspaces", "at": (cg, ""), "shots": [{"tag": "switcher", "click": ".ds-ws > button", "only": "16x9"}]},
        {"n": 10, "name": "estate-at-a-glance", "at": (cg, ""), "shots": [{"tag": "top"}, {"tag": "inside-a-model", "scroll": ".ds-dash.b"}]},
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8765")
    ap.add_argument("--only", nargs="*", type=int, default=[])
    ap.add_argument("--out", default=str(ROOT / "out" / "moments"))
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("pip install playwright  (it uses the Edge or Chrome already installed)"); return 2
    runfile = ROOT / "out" / "demo-run.json"
    run = json.loads(runfile.read_text(encoding="utf-8")) if runfile.exists() else {}
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    done, skipped = [], []
    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "chrome"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True); break
            except Exception:
                continue
        if browser is None:
            print("no Edge or Chrome found for Playwright to drive"); return 2
        for m in moments(run):
            if a.only and m["n"] not in a.only:
                continue
            if not m["at"]:
                skipped.append(f"{m['n']} {m['name']}: its question has not been asked (python tools/demo.py run)"); continue
            ws, page_path = m["at"]
            for frame, (w, h, scale) in FRAMES.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, reduced_motion="reduce", color_scheme="dark")
                page = ctx.new_page()
                page.goto(f"{a.base}/app/?capture=1#/e/{ws}" + (f"/{page_path}" if page_path else ""), wait_until="networkidle")
                page.wait_for_selector(".ds-main", timeout=20000)
                page.wait_for_timeout(1500)                               # the page fetches its panels after first paint
                for s in m["shots"]:
                    if s.get("only") and s["only"] != frame:
                        continue
                    try:
                        if s.get("click"):
                            page.locator(s["click"]).first.click(timeout=8000); page.wait_for_timeout(700)
                        if s.get("scroll"):
                            page.locator(s["scroll"]).first.evaluate("el => { const m = document.querySelector('.ds-main'); m.scrollTop = el.getBoundingClientRect().top + m.scrollTop - 70 }")
                            page.wait_for_timeout(500)
                        else:
                            page.evaluate("document.querySelector('.ds-main').scrollTop = 0")
                        name = f"{m['n']:02d}-{m['name']}-{s['tag']}-{frame}.png"
                        page.screenshot(path=str(out / name))
                        done.append(name)
                    except Exception as e:
                        skipped.append(f"{m['n']} {m['name']} {s['tag']} {frame}: {str(e).splitlines()[0][:120]}")
                ctx.close()
        browser.close()
    print(f"{len(done)} frames in {out}")
    for s in skipped:
        print("  skipped:", s)
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
