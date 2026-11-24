"""The getting-started guide (Karim, 2026-11-24): for someone who has just been handed a login. One spec; the app
shows it, and one self-contained HTML file carries it to send or print. Arrows are drawn over real captures from
positions found on the page at capture time; every word is text."""
import sys, pathlib, json, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth
from anaplan_architect import guide as guidemod
from test_access import _login, _no_real_backend      # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ["sign-in", "workspaces", "make-a-workspace", "documents", "ask", "read-an-answer", "concise-and-full", "build-plans", "what-a-change-touches", "notes",
        "what-it-cannot-see", "spend", "tracing", "who-to-ask"]


def test_the_guide_follows_the_path_a_new_person_meets_in_plain_words():
    spec = guidemod.spec()
    assert [s["id"] for s in spec["sections"]] == PATH
    text = json.dumps(spec, ensure_ascii=False)
    assert "—" not in text and "curious" not in text.lower()                 # no em dash, and never that word
    for s in spec["sections"]:
        assert s["title"] and s["body"] and all(len(p) < 420 for p in s["body"]), s["id"]
        for sc in s.get("screens") or []:
            assert 1 <= len(sc["callouts"]) <= 3, f"{s['id']}: two or three callouts a screen, not ten"
            assert all(c["sel"] and c["text"] for c in sc["callouts"]) and sc["alt"]
    berts = [s["bert"] for s in spec["sections"] if s.get("bert")]
    assert set(berts) <= guidemod.BERTS                                           # existing poses only, at most one a section
    ask = next(s for s in spec["sections"] if s["id"] == "ask")
    assert len(guidemod.questions()) == 8 and ask.get("questions") is True       # the eight showcase questions, read from the demo's own list
    who = next(s for s in spec["sections"] if s["id"] == "who-to-ask")
    assert "linkedin.com/in/karimlameer" in who["link"]["href"] and "@" not in json.dumps(who)


def test_every_login_can_open_it_and_it_is_shown_once_until_dismissed(tmp_path):
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    pw = admin.post("/api/admin/users", json={"username": "alice", "name": "Alice", "demo": False}).json()["password"]
    alice = _login(app, "alice", pw)
    g = alice.get("/api/guide")
    assert g.status_code == 200 and [s["id"] for s in g.json()["sections"]] == PATH and len(g.json()["questions"]) == 8
    assert TestClient(app).get("/api/guide").status_code == 401                    # an instance with logins: signed in first
    # shown once: not seen yet, then dismissed, and that is remembered for this login only
    assert alice.get("/api/prefs").json()["guide_seen"] is False
    assert alice.put("/api/prefs", json={"guide_seen": True}).json()["guide_seen"] is True
    assert alice.get("/api/prefs").json()["guide_seen"] is True and admin.get("/api/prefs").json()["guide_seen"] is False
    assert alice.put("/api/prefs", json={"answer_mode": "concise"}).json()["guide_seen"] is True      # another setting does not bring it back


def test_the_generated_guide_is_resolved_from_real_screens(tmp_path):
    """What tools/guide.py wrote: every screen has its image, and every callout a place on it that was found on the page."""
    g = guidemod.built()
    assert g is not None, "run tools/guide.py: the guide has not been generated"
    img = pathlib.Path(guidemod.__file__).parent.parent / "static" / "guide" / "img"
    n = 0
    for s in g["sections"]:
        for sc in s.get("screens") or []:
            assert (img / sc["image"]).is_file() and sc["width"] > 0 and sc["height"] > 0, sc["name"]
            for c in sc["callouts"]:
                assert 0 <= c["x"] <= 1 and 0 <= c["y"] <= 1 and 0 <= c["tx"] <= 1 and 0 <= c["ty"] <= 1 and c["n"] >= 1 and c["text"], (sc["name"], c)
                n += 1
    assert n >= 25 and [s["id"] for s in g["sections"]] == PATH
    # the app serves the images it names
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    first = next(sc for s in g["sections"] for sc in s.get("screens") or [])
    r = c.get("/app/guide/img/" + first["image"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")


def test_the_file_to_send_or_print_makes_no_outside_request():
    f = ROOT / "docs" / "onboarding" / "getting-started.html"
    assert f.is_file(), "run tools/guide.py: docs/onboarding/getting-started.html has not been generated"
    html = f.read_text(encoding="utf-8")
    # nothing is fetched: no script, no stylesheet, no font, no image from anywhere but the file itself
    assert not re.search(r"<script\b|<link\b|@import|<iframe\b|<object\b|<embed\b", html, re.I)
    assert not re.search(r"""(?:src|srcset|poster)\s*=\s*["']?\s*(?!data:)[^"'\s>]""", html, re.I)
    assert not re.search(r"url\(\s*['\"]?(?!data:|#)", html, re.I)            # url(#ah) is the arrowhead inside the same picture, not a fetch
    hrefs = re.findall(r'href="([^"]+)"', html)
    assert all(h.startswith("#") or h == "https://linkedin.com/in/karimlameer" for h in hrefs)          # the one link out is a link, not a request
    assert html.count("data:image/png;base64,") >= 12 and "—" not in html and "curious" not in html.lower()
    g = guidemod.built()
    for s in g["sections"]:
        assert s["title"] in html
        for sc in s.get("screens") or []:
            for c in sc["callouts"]:
                assert c["text"].replace("&", "&amp;") in html or c["text"] in html                      # a callout is text, not part of the picture
    assert 'name="viewport"' in html and "prefers-reduced-motion" not in html and "animation" not in html and "transition" not in html
