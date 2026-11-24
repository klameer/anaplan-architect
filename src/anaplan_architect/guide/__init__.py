"""The getting-started guide: for someone who has just been handed a login, not for an engineer.

It is written once, in spec.json: the sections in the order a new person meets them, each with a few plain lines and,
where a screen helps, the screen and two or three things to point at on it. `tools/guide.py` turns that into what is
shown: it takes each screen from the capture store (Caldergate, demo logins only), finds where each callout points by
looking the element up on the real page, and writes

  static/guide/guide.json and static/guide/img/*.png    what the app shows at #/guide
  docs/onboarding/getting-started.html                  the same guide as one file, to send or print

So an arrow can never point at where a button used to be: rerun the command and it points at where the button is.
Every word, callouts included, is text, never part of a picture: it can be read aloud, searched and translated.
"""
from __future__ import annotations
import base64, html, json
from pathlib import Path

HERE = Path(__file__).parent
STATIC = HERE.parent / "static" / "guide"
BERTS = {"hello", "information", "evidence", "neutral", "processing", "warning", "question", "investigating", "error"}       # the poses the brand kit has: no new ones


def spec() -> dict:
    return json.loads((HERE / "spec.json").read_text(encoding="utf-8"))


def questions() -> list[dict]:
    """The showcase questions, from the demo's own list: the things to ask first."""
    from ..orac import demo as demomod
    root = demomod.root()
    if root is None:
        return []
    man = json.loads((Path(root) / "demo.json").read_text(encoding="utf-8"))
    return [{"text": q["text"], "shows": q.get("feature") or ""} for q in man.get("showcase") or []]


def built() -> dict | None:
    """The guide as tools/guide.py last wrote it (screens resolved), or None when it has not been generated."""
    f = STATIC / "guide.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def for_app() -> dict:
    """What the app shows: the generated guide; before it has been generated, the words alone, without screens."""
    g = built()
    if g is None:
        g = spec()
        for s in g["sections"]:
            s.pop("screens", None)
    g["questions"] = questions()
    return g


# ---------- the one-file version ----------
CSS = """
:root{--bg:#0b0e0d;--card:#141917;--rule:#2a3430;--ink:#e8ebe9;--muted:#9aa5a0;--accent:#34d399;--amber:#fbbf24}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:28px 18px 60px}
h1{font-size:30px;line-height:1.2;margin:0 0 10px;font-weight:600}
h2{font-size:21px;line-height:1.3;margin:0 0 10px;font-weight:600}
p{margin:0 0 12px}
.lead{font-size:18px;color:var(--ink)}
.from{color:var(--muted);font-size:14px;margin-bottom:26px}
nav{border:1px solid var(--rule);border-radius:10px;padding:14px 18px;margin:0 0 30px;background:var(--card)}
nav ol{margin:6px 0 0;padding-left:22px;columns:2;column-gap:28px}
nav a,.out{color:var(--accent)}
section{border-top:1px solid var(--rule);padding:28px 0 6px}
.num{font:600 12px/1 ui-monospace,Consolas,monospace;color:var(--accent);letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px}
.head{display:flex;gap:14px;align-items:flex-start}
.head img{flex:none;width:52px;height:auto}
ul{margin:0 0 12px;padding-left:22px}
li{margin-bottom:6px}
figure{margin:16px 0 20px}
.shot{position:relative;border:1px solid var(--rule);border-radius:10px;overflow:hidden;background:#000;line-height:0}
.shot img{display:block;width:100%;height:auto}
.shot svg{position:absolute;inset:0;width:100%;height:100%}
ol.calls{margin:12px 0 0;padding:0;list-style:none}
ol.calls li{display:flex;gap:10px;align-items:flex-start;margin-bottom:8px;font-size:15px}
ol.calls b{flex:none;width:24px;height:24px;border-radius:50%;background:var(--amber);color:#1a1200;font:600 13px/24px system-ui,sans-serif;text-align:center}
.q{border:1px solid var(--rule);border-radius:8px;padding:10px 14px;margin-bottom:8px;background:var(--card)}
.q span{display:block;color:var(--muted);font-size:13.5px}
footer{border-top:1px solid var(--rule);margin-top:26px;padding-top:16px;color:var(--muted);font-size:13.5px}
@media (max-width:600px){body{font-size:15.5px}nav ol{columns:1}h1{font-size:25px}.head img{width:40px}}
@media print{:root{--bg:#fff;--card:#fff;--rule:#bbb;--ink:#111;--muted:#444;--accent:#0a6b4a}body{font-size:11.5pt}nav{break-after:page}section{break-inside:avoid-page}figure{break-inside:avoid}}
"""


def overlay(screen: dict) -> str:
    """The numbered arrows over one screen, as SVG in the screen's own pixels: a line from the number to what it points at."""
    w, h = screen["width"], screen["height"]
    r = max(13, round(w * 0.0135))
    out = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true" focusable="false">',
           '<defs><marker id="ah" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#fbbf24"/></marker></defs>']
    for c in screen["callouts"]:
        x, y, tx, ty = c["x"] * w, c["y"] * h, c["tx"] * w, c["ty"] * h
        out.append(f'<line x1="{tx:.0f}" y1="{ty:.0f}" x2="{x:.0f}" y2="{y:.0f}" stroke="#0b0e0d" stroke-width="{r * 0.5:.0f}" stroke-linecap="round" opacity=".55"/>')
        out.append(f'<line x1="{tx:.0f}" y1="{ty:.0f}" x2="{x:.0f}" y2="{y:.0f}" stroke="#fbbf24" stroke-width="{max(3, r * 0.22):.0f}" marker-end="url(#ah)"/>')
        out.append(f'<circle cx="{tx:.0f}" cy="{ty:.0f}" r="{r}" fill="#fbbf24" stroke="#0b0e0d" stroke-width="3"/>')
        out.append(f'<text x="{tx:.0f}" y="{ty + r * 0.38:.0f}" text-anchor="middle" font-family="system-ui,sans-serif" font-weight="600" font-size="{r * 1.1:.0f}" fill="#1a1200">{c["n"]}</text>')
    out.append("</svg>")
    return "".join(out)


def to_html(g: dict, images: dict[str, bytes], berts: dict[str, bytes], qs: list[dict]) -> str:
    """One self-contained page: styles inline, images inline, no script, nothing fetched. Reads at phone width and prints."""
    e = html.escape
    uri = lambda b, mime: f"data:{mime};base64," + base64.b64encode(b).decode("ascii")
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             f"<title>{e(g['title'])}</title><style>{CSS}</style></head><body><main>",
             f"<h1>{e(g['title'])}</h1><p class=\"lead\">{e(g['lead'])}</p><p class=\"from\">{e(g['from'])}</p>",
             '<nav aria-label="In this guide"><b>In this guide</b><ol>' + "".join(f'<li><a href="#{e(s["id"])}">{e(s["title"])}</a></li>' for s in g["sections"]) + "</ol></nav>"]
    for i, s in enumerate(g["sections"], 1):
        parts.append(f'<section id="{e(s["id"])}"><div class="num">Step {i} of {len(g["sections"])}</div><div class="head">')
        if s.get("bert") and s["bert"] in berts:
            parts.append(f'<img src="{uri(berts[s["bert"]], "image/svg+xml")}" alt="" width="52" height="45">')
        parts.append(f"<div><h2>{e(s['title'])}</h2></div></div>")
        parts += [f"<p>{e(p)}</p>" for p in s["body"]]
        if s.get("list"):
            parts.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in s["list"]) + "</ul>")
        if s.get("questions"):
            parts += [f'<div class="q">{e(q["text"])}<span>{e(q["shows"])}</span></div>' for q in qs]
        for sc in s.get("screens") or []:
            parts.append(f'<figure><div class="shot"><img src="{uri(images[sc["image"]], "image/png")}" alt="{e(sc["alt"])}" width="{sc["width"]}" height="{sc["height"]}">{overlay(sc)}</div>')
            parts.append('<ol class="calls">' + "".join(f"<li><b>{c['n']}</b><span>{e(c['text'])}</span></li>" for c in sc["callouts"]) + "</ol></figure>")
        if s.get("link"):
            parts.append(f'<p><a class="out" href="{e(s["link"]["href"])}">{e(s["link"]["text"])}</a></p>')
        parts.append("</section>")
    parts.append(f"<footer>Every screen is from the Caldergate demo: an invented company. Made from the app as it was on {e(g.get('captured') or '')}.</footer></main></body></html>")
    return "".join(parts)
