"""Security review of everything since 13 November except sharing (2026-11-24, at bf13414). One test per finding,
written to fail first."""
import sys, pathlib, json, io, zipfile, threading, re, csv, time
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth
from test_access import _login, _workspace, _no_real_backend, _B, FX      # noqa: F401
from test_review_sharing import Model, _setup, _rezip, _restore


@pytest.fixture()
def s(tmp_path):
    return _setup(tmp_path)


def _exports(change):
    rows = list(csv.reader(io.StringIO((FX / "1 Caldergate Planning" / "Line Items.csv").read_text(encoding="utf-8"))))
    buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows([change(list(r)) for r in rows])
    return buf.getvalue().encode("utf-8")


# ---------- H1 ----------
HOSTILE = '[x](#" onmouseover="document.title=document.cookie" style="position:fixed;inset:0;display:block)'


def test_h1_a_name_in_an_export_is_never_markup_on_the_report_page(s):
    from html.parser import HTMLParser
    app, model, c, ids = s
    alice = c["alice"]
    for what, change in (("module", lambda r: [x.replace("CAL02 Revenue", HOSTILE) for x in r]), ("line item", lambda r: [x.replace("Gross Revenue", HOSTILE) for x in r]),
                         ("notes", lambda r: (r.__setitem__(10, HOSTILE) or r) if r and r[0] == "Units" and len(r) > 10 else r),
                         ("script", lambda r: [x.replace("Gross Revenue", '[x](#"><script>alert(1)</script>)') for x in r]),
                         ("link out", lambda r: [x.replace("Gross Revenue", "[x](#x) [y](javascript:alert(1))") for x in r])):
        up = alice.post("/api/estates", data={"name": "W " + what, "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", _exports(change), "text/csv"))])
        assert up.status_code == 200, (what, up.text[:200])
        r = alice.get(f"/api/estates/{up.json()['id']}/report")
        assert r.status_code == 200
        seen = []

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs): seen.append((tag, dict(attrs)))
            handle_startendtag = handle_starttag
        P().feed(r.text)
        for tag, attrs in seen:
            assert not [k for k in attrs if k.startswith("on")], (what, tag, attrs)
            assert tag != "a" or (set(attrs) <= {"href", "class", "id"} and re.fullmatch(r"#[\w.:%-]*", attrs.get("href", "#"))), (what, attrs)
            assert "position" not in (attrs.get("style") or "") and "inset" not in (attrs.get("style") or ""), (what, tag, attrs)
        scripts = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", r.text, re.S)
        assert len(scripts) == 1 and "alert(1)" not in "".join(scripts)
        # the page's own policy: its one script by hash, no inline script or handler otherwise, and no origin of its own
        csp = r.headers["content-security-policy"]
        src = csp.split("script-src")[1].split(";")[0]
        assert "unsafe-inline" not in src and "unsafe-hashes" not in src and src.strip().startswith("'sha256-") and "sandbox allow-scripts" in csp and "allow-same-origin" not in csp
        import base64, hashlib
        assert "'sha256-" + base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode() + "'" in src
    # a report with nothing hostile in it is served as the library wrote it
    from anaplan_architect import reportpage
    clean = alice.get(f"/api/estates/{_workspace(alice, 'clean')}/report").text
    assert reportpage.safe(clean) == (clean, 0)
