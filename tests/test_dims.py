"""Orac backlog 18: dimension inference and cell cost. Sizes solved from cell counts on the fixture (every one reproduced),
the axes a formula requires against the axes a line item applies to (references, SELECT, LOOKUP, SUM, time and version
functions), the cells an unneeded axis costs, and the model-level export convention where a blank Applies To means the
module's dimensions: sized as one unnamed factor, judged on Time and Versions only."""
import sys, pathlib, csv, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_estate import fleet
from anaplan_architect.orac import dims
from anaplan_architect.orac.evidence import Evidence
from anaplan_architect.store import Workspace
from anaplan_architect import tools
from anaplan_architect.web import create_app
from test_web import _Fake, _upload, FX

COLS = ["", "Format", "Formula", "Summary", "Applies To", "Time Scale", "Time Range", "Versions", "Style", "Cell Count", "Notes", "Referenced By", "Module Name"]
NUM = '{"dataType":"NUMBER"}'
BOOL = '{"dataType":"BOOLEAN"}'
ENT = '{"dataType":"ENTITY"}'
NA = "Not Applicable"


def _row(name, fmt="", formula="", applies="", scale=NA, rng=NA, versions=NA, cells=0, module=""):
    return [name, fmt, formula, "", applies, scale, rng, versions, "", str(cells), "", "", module]


def _synth(tmp_path) -> pathlib.Path:
    """A model with T = 26 periods, Products 4, Regions 5, Versions 3, and one module in the model-level export style
    (blank Applies To, an unnamed bundle of 355 cells)."""
    rows = [COLS,
            _row("SYS00 Settings"),
            _row("Rate", NUM, "", "", NA, NA, NA, 1, "SYS00 Settings"),
            _row("Is Month?", BOOL, "START() > DATE(2020, 1, 1)", "", "Month", "Model Calendar", NA, 26, "SYS00 Settings"),
            _row("Version Flag", BOOL, "ISCURRENTVERSION()", "", NA, NA, "All", 3, "SYS00 Settings"),
            _row("INP01 Data"),
            _row("Units", NUM, "", "Products, Regions", "Month", "Model Calendar", NA, 520, "INP01 Data"),
            _row("Price", NUM, "", "Products", "Month", "Model Calendar", NA, 104, "INP01 Data"),
            _row("Region Map", ENT, "", "Regions", NA, NA, NA, 5, "INP01 Data"),
            _row("CAL01 Calc"),
            _row("Revenue", NUM, "'INP01 Data'.Units * 'INP01 Data'.Price", "Products, Regions", "Month", "Model Calendar", NA, 520, "CAL01 Calc"),
            _row("Rate Repeated", NUM, "'SYS00 Settings'.Rate", "Products, Regions", "Month", "Model Calendar", NA, 520, "CAL01 Calc"),
            _row("Price Jan", NUM, "'INP01 Data'.Price[SELECT: TIME.'Jan 24']", "Products", "Month", "Model Calendar", NA, 104, "CAL01 Calc"),
            _row("Region Total", NUM, "'INP01 Data'.Units[SUM: 'INP01 Data'.Region Map]", "Regions", "Month", "Model Calendar", NA, 130, "CAL01 Calc"),
            _row("Lookup Price", NUM, "'INP01 Data'.Price[LOOKUP: 'INP01 Data'.Region Map]", "Regions", "Month", "Model Calendar", NA, 130, "CAL01 Calc"),
            _row("Prev Revenue", NUM, "PREVIOUS(Revenue)", "Products, Regions", "Month", "Model Calendar", NA, 520, "CAL01 Calc"),
            _row("Ghost", NUM, "Missing + 1", "Products", "Month", "Model Calendar", NA, 104, "CAL01 Calc"),
            _row("Period Map", '{"dataType":"TIME_ENTITY"}', "", "Products", NA, NA, NA, 4, "CAL01 Calc"),
            _row("By Period", NUM, "'INP01 Data'.Price[SUM: Period Map]", "", "Month", "Model Calendar", NA, 26, "CAL01 Calc"),
            _row("C BIG Report"),
            _row("A", NUM, "", "", NA, NA, NA, 355, "C BIG Report"),
            _row("B", NUM, "A * 2", "", "Month", "Model Calendar", NA, 355 * 26, "C BIG Report"),
            _row("C", NUM, "'SYS00 Settings'.Rate", "", NA, NA, "All", 355 * 3, "C BIG Report")]
    d = tmp_path / "estate" / "1 Synth Model"
    d.mkdir(parents=True)
    with open(d / "Line Items.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)
    return tmp_path / "estate"


def test_sizes_solve_from_cell_counts_on_the_fixture():
    er = fleet.run(FX)
    m = next(x for x in er.models if x.name == "Caldergate Planning")
    md = dims.ModelDims(m, "s1")
    s = md.summary()
    sizes = {x["factor"]: x for x in s["sizes"]}
    assert sizes["Segments"]["size"] == 3 and sizes["Regions"]["size"] == 10 and sizes["Departments"]["size"] == 5
    assert sizes["Time (Month, Model Calendar)"]["size"] == 24 and sizes["Segments"]["agreement"] == 1.0 and sizes["Segments"]["evidence"] >= 10
    assert s["explained"] == {"items": 30, "of": 30, "share": 1.0} and s["cells"] == 7787 and s["has_cells"]
    ax = {a["axis"]: a for a in s["axes"]}
    assert ax["Time"]["size"] == 24 and ax["Time"]["marginal"] == 7429 and ax["Regions"]["marginal"] == 5859 and ax["Time"]["kind"] == "time"
    # a module whose blank line items truly carry no dimension sizes to 1 and is no axis at all
    assert sizes["[dimensions of SYS00 Model Settings]"]["size"] == 1 and "[dimensions of SYS00 Model Settings]" not in ax
    # the one over-dimensioned item: the Segment mapping repeats one value per Region
    over = {r["ref"]: r for r in s["over"]}
    assert list(over) == ["CAL02 Revenue.Segment"] and over["CAL02 Revenue.Segment"]["extra"] == ["Regions"] and over["CAL02 Revenue.Segment"]["saved_cells"] == 27
    assert s["over_summary"]["items"] == 1 and s["over_summary"]["saved"] == 27 and s["over_summary"]["lists_unjudged"] == 0
    # judged in full: applied equals required
    j = md.item("CAL04 Margin.Margin %")
    assert j["applied"] == ["Segments", "Time"] and j["required"] == ["Segments", "Time"] and j["extra"] == [] and j["judged"] and j["lists_judged"]
    assert j["axis_sizes"] == {"Segments": 3, "Time": 24} and j["id"] == md.cite("CAL04 Margin.Margin %")
    # a SUM aggregates to a list the export does not name: the unmatched own axis is taken as the target
    nr = md.item("CAL04 Margin.Net Revenue")
    assert nr["sums"] == 1 and nr["extra"] == [] and nr["unplaced"] == ["Segments"] and "taken as the target" in nr["reason"]
    assert s["not_judged"] == {"1 reference(s) the export does not contain": 1}
    assert any("reproduce 30 of 30" in c for c in s["coverage"])


def test_required_axes_follow_references_select_lookup_sum_and_functions(tmp_path):
    er = fleet.run(_synth(tmp_path))
    m = er.models[0]
    md = dims.ModelDims(m, "s1")
    s = md.summary()
    sizes = {x["factor"]: x for x in s["sizes"]}
    assert sizes["Products"]["size"] == 4 and sizes["Regions"]["size"] == 5 and sizes["Time (Month, Model Calendar)"]["size"] == 26 and sizes["Versions"]["size"] == 3
    assert sizes["[dimensions of C BIG Report]"]["size"] == 355 and sizes["[dimensions of SYS00 Settings]"]["size"] == 1
    assert s["explained"]["share"] == 1.0
    it = {k: md.item(k) for k in md.items}
    assert it["CAL01 Calc.Revenue"]["extra"] == [] and it["CAL01 Calc.Revenue"]["required"] == ["Products", "Regions", "Time"]
    rr = it["CAL01 Calc.Rate Repeated"]
    assert rr["extra"] == ["Products", "Regions", "Time"] and rr["constant"] and rr["saved_cells"] == 519 and rr["lists_judged"]
    pj = it["CAL01 Calc.Price Jan"]
    assert pj["required"] == ["Products"] and pj["extra"] == ["Time"] and pj["saved_cells"] == 100           # SELECT on Time removes Time
    rt = it["CAL01 Calc.Region Total"]
    assert rt["sums"] == 1 and rt["extra"] == [] and rt["unplaced"] == ["Regions"] and rt["implicit"] == ["Products"]   # SUM: Regions is the target; Products aggregated implicitly
    lp = it["CAL01 Calc.Lookup Price"]
    assert lp["required"] == ["Regions", "Time"] and lp["extra"] == []                                       # LOOKUP brings the mapping's axis in place of Products
    assert it["CAL01 Calc.Prev Revenue"]["extra"] == [] and "Time" in it["CAL01 Calc.Prev Revenue"]["required"]   # PREVIOUS needs Time
    assert it["SYS00 Settings.Is Month?"]["extra"] == [] and it["SYS00 Settings.Version Flag"]["extra"] == [] and it["SYS00 Settings.Version Flag"]["required"] == ["Versions"]
    assert not it["CAL01 Calc.Ghost"]["judged"] and "does not contain" in it["CAL01 Calc.Ghost"]["reason"]
    bp = it["CAL01 Calc.By Period"]                                                                            # a SUM by a time-period mapping aggregates into Time
    assert bp["required"] == ["Time"] and bp["extra"] == [] and bp["sums"] == 0 and bp["judged"] and bp["lists_judged"]
    # the model-level export convention: blank Applies To = the module's dimensions, unnamed; Time and Versions still judged
    b = it["C BIG Report.B"]
    assert b["applied"] == ["[dimensions of C BIG Report]", "Time"] and not b["lists_judged"] and b["extra"] == ["Time"] and b["saved_cells"] == 355 * 26 - 355
    c = it["C BIG Report.C"]
    assert c["extra"] == ["Versions"] and c["saved_cells"] == 355 * 3 - 355 and c["constant"] and c["axis_sizes"]["[dimensions of C BIG Report]"] == 355
    over = [r["ref"] for r in s["over"]]
    assert over[:2] == ["C BIG Report.B", "C BIG Report.C"] and set(over) == {"C BIG Report.B", "C BIG Report.C", "CAL01 Calc.Rate Repeated", "CAL01 Calc.Price Jan"}
    assert s["over_summary"]["saved"] == 8875 + 710 + 519 + 100 and s["over_summary"]["lists_unjudged"] == 2
    ax = {a["axis"]: a for a in s["axes"]}
    assert ax["[dimensions of C BIG Report]"]["kind"] == "module" and ax["[dimensions of C BIG Report]"]["marginal"] == (9230 - 26) + (1065 - 3) + (355 - 1)
    assert any("blank on 7 of" in c and "1 module(s) carry their dimensions as one sized factor" in c for c in s["coverage"])


def test_size_tool_cites_and_the_api_serves_the_page(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws"); w.snapshot_id = "s1"
    tb = tools.Toolbox(w, Evidence("e", "s1"))
    r = json.loads(tb.call("size", {"model": "Caldergate Planning"}))
    assert r["cells"] == 7787 and r["over_dimensioned"][0]["ref"] == "CAL02 Revenue.Segment" and r["over_dimensioned"][0]["saved_cells"] == 27
    assert "CAL02 Revenue.Segment" in r["cites"] and "Caldergate Planning" in r["cites"] and r["sizes"][0]["factor"] == "Segments"
    one = json.loads(tb.call("size", {"name": "CAL04 Margin.Margin %"}))
    assert one["applied"] == ["Segments", "Time"] and one["extra"] == [] and one["model"] == "Caldergate Planning" and "CAL04 Margin.Margin %" in one["cites"]
    assert json.loads(tb.call("size", {"model": "Nope"}))["error"].startswith("no model")
    assert any(t["name"] == "size" for t in tools.Toolbox.schema())
    # the routes, and the drawer: a line item's evidence carries its axes
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    s = c.get(f"/api/estates/{eid}/size").json()
    assert s["model"] == "Caldergate Planning" and s["explained"]["share"] == 1.0 and s["over"][0]["id"] and s["snapshot"]
    hr = c.get(f"/api/estates/{eid}/size", params={"model": "Caldergate HR Model"}).json()
    assert hr["model"] == "Caldergate HR Model" and hr["cells"] == 1033
    j = c.get(f"/api/estates/{eid}/size/item", params={"model": "Caldergate Planning", "ref": "CAL02 Revenue.Segment"}).json()
    assert j["extra"] == ["Regions"] and j["saved_cells"] == 27
    assert c.get(f"/api/estates/{eid}/size/item", params={"model": "Caldergate Planning", "ref": "Nope.Nope"}).status_code == 404
    ev = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL02 Revenue.Segment"}).json()
    assert ev["object"]["axes"]["extra"] == ["Regions"] and ev["object"]["axes"]["applied"] == ["Regions", "Segments"]
    assert (s["snapshot"], "Caldergate Planning") in app.state.dims
