"""Three gaps the use case runs of 2026-09-29 exposed in the verdict: a figure written in backticks escaped the numeral
guard; the keys the tools hand out for decisions (action-plan and size keys) were flagged as names not found; a formula
fragment in backticks was flagged too.

The second pass, from use cases 4 to 7 the same day: list members quoted from a formula (`Accounts.'6100 Rent'`, a version
name) were names not found; a model's spine written as `Cost Centres by Accounts by Month` was too; the number of a heading
(`### 3.2`) was an untraced figure; an estate total added up over four models was untraced; and the processes the actions
tool lists were never handed as evidence, so an answer naming them scored unchecked."""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect.orac.evidence import figures
from anaplan_architect.chat import assess_answer, _member_refs, _members
from anaplan_architect.store import Workspace
from anaplan_architect.tools import Toolbox
from test_web import FX


def test_a_figure_in_backticks_is_checked_like_prose():
    text = ("`CAL04 Margin.Margin %` has `5,017,824` cells and `16.0%` of the effort; the two constants save `593,711 + 593,711 = 1,187,422` "
            "cells between them, and `2021` was the year.")
    f = figures(text, ["cells 5017824; effort 16.0; saved 593711"])
    assert f["checked"] == 5 and f["traced"] == 4 and f["derived"] == 1 and f["untraced"] == [] and f["benign"] == 1
    # a figure the tools never returned is still caught inside backticks; a name with digits in it is still a name
    g = figures("It carries `7,777,777` cells; see `CAL04 Margin`.", ["cells 5017824"])
    assert g["untraced"] == ["7,777,777"] and g["checked"] == 1


def test_handles_axes_and_formula_fragments_are_not_names_not_found(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    text = ("Set `hotspot-investigate:Caldergate HR` or `action:hotspot-investigate:Caldergate HR` and "
            "`size:Caldergate Planning::CAL02 Revenue.Segment`; `Time` and `Versions` carry the cells; `Net Revenue - Margin` and "
            "`NOT Margin` are formulas; `Ghost.Nope` is not real.")
    a = assess_answer(text, w)
    assert a["unverified"] == ["Ghost.Nope"]
    for h in ("hotspot-investigate:Caldergate HR", "action:hotspot-investigate:Caldergate HR", "size:Caldergate Planning::CAL02 Revenue.Segment",
              "Time", "Versions", "Net Revenue - Margin", "NOT Margin"):
        assert h not in a["unchecked"] and h not in a["unverified"], h
    # a real name the architect never looked up is still unchecked, and an invented expression is still not found
    b = assess_answer("`CAL04 Margin.Margin` and `Fairy Dust - Unicorns`.", w)
    assert b["unchecked"] == ["CAL04 Margin.Margin"] and b["unverified"] == ["Fairy Dust - Unicorns"]


def test_list_members_a_formula_names_are_formula_literals_not_missing_names(tmp_path):
    refs = list(_member_refs("IF ITEM(Accounts) = Accounts.'6100 Rent' THEN 'INP02 Opex Drivers'.Rent ELSE 'INP01 Volumes'.'Discount %' "
                             "+ Versions.Actual + x[SELECT: Versions.'Budget v2 DO NOT USE']", {"accounts", "versions"}))
    assert refs == [("Accounts", "6100 Rent"), ("Versions", "Actual"), ("Versions", "Budget v2 DO NOT USE")]
    w = Workspace.open(FX, tmp_path / "ws")
    members, lists = _members(w)
    assert {"departments", "regions", "segments", "versions", "time"} <= lists
    w.__dict__["_members"] = (members | {"accounts.6100 rent", "6100 rent", "versions.budget v2 do not use", "budget v2 do not use"}, lists)
    a = assess_answer("Check `Accounts.'6100 Rent'`, `Budget v2 DO NOT USE` and `Segments.'Enterprise'`; `Fairy.'Dust'` and `Base` are not real.", w)
    assert a["unverified"] == ["Fairy.'Dust'", "Base"] and a["unchecked"] == []


def test_dimensions_joined_by_by_and_time_granularities_are_not_missing_names(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    a = assess_answer("The spine is `Departments by Regions by Month by Versions`; `Departments by Unicorns` is not.", w)
    assert a["unverified"] == ["Departments by Unicorns"] and a["unchecked"] == []


def test_heading_and_list_numbers_are_structure_not_figures():
    f = figures("### 3.2 Proposed line items\n\n12. Reconcile `X`\n15. Ask Dan\n### 5.4 Workforce effort\nIt has 42 cells.", ["cells 42"])
    assert f["checked"] == 1 and f["traced"] == 1 and f["untraced"] == []
    # a real figure that merely starts a line is still a figure
    g = figures("1,000 cells sit on it.", [])
    assert g["untraced"] == ["1,000"]


def test_a_total_over_several_figures_is_derived():
    text = ("| Model | Cells |\n|---|---:|\n| A | 130,001,662 |\n| B | 8,060,698 |\n| C | 6,343,559 |\n| D | 137,882 |\n\n"
            "Total exported cells across the four models are 144,543,801.")
    f = figures(text, ["cells 130001662", "cells 8060698", "cells 6343559", "cells 137882"])
    assert f["traced"] == 4 and f["derived"] == 1 and f["untraced"] == []
    # a total no figures add up to is still untraced
    h = figures(text.replace("144,543,801", "150,000,000"), ["cells 130001662", "cells 8060698", "cells 6343559", "cells 137882"])
    assert h["untraced"] == ["150,000,000"]


def test_processes_the_actions_tool_lists_are_handed_as_evidence(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    tb = Toolbox(w)
    r = tb.actions("Caldergate Planning")
    procs = {p for a in r["actions"] for p in a["processes"]}
    assert "Load Actuals" in procs and tb.ev.lookup("Load Actuals") is not None
    a = assess_answer("Run `Load Actuals` after `Import Actuals from NetSuite`.", w, tb.ev)
    assert [c["as_written"] for c in a["cited"]] == ["Load Actuals", "Import Actuals from NetSuite"] and a["unchecked"] == []


def test_external_sources_inferred_from_import_names_are_known(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    assert set(w.estate.external) == {"NetSuite", "Treasury file"}
    a = assess_answer("`NetSuite` and `Treasury file` feed it; `Caldergate Hub v1` never did.", w)
    assert a["unchecked"] == ["NetSuite", "Treasury file"] and a["unverified"] == ["Caldergate Hub v1"]


def test_a_compact_figure_in_a_source_traces_the_answer_that_copies_it():
    from anaplan_architect.orac.evidence import numbers_in
    assert numbers_in("- Opex module: 30.1M (23.2%); 666K; 10.9bn; 5 models; 3 bn; 1,000") == [30.1e6, 23.2, 666e3, 10.9e9, 5.0, 3e9, 1000.0]
    f = figures("`CAL03 Opex` holds 30.1M cells and `Data - Employees` 666K.", ["- CAL03 Opex: 30.1M (23.2%)", "- Data - Employees: 666K (10.5%)"])
    assert f["checked"] == 2 and f["traced"] == 2 and f["untraced"] == []


def test_the_size_tool_ranks_the_modules_by_exact_cells_and_cites_them(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    tb = Toolbox(w)
    out = tb.size(model="Caldergate Planning")
    mods = out["modules"]
    assert mods and mods == sorted(mods, key=lambda r: (-r["cells"], r["module"])) and sum(r["cells"] for r in mods) == out["cells"]
    assert abs(sum(r["share"] for r in mods) - 100) < 0.5 and all(r["line_items"] > 0 for r in mods)
    m = w.models()["Caldergate Planning"]
    top = mods[0]
    assert top["cells"] == sum(li.cell_count for li in m.model.line_items.values() if li.module == top["module"] and not li.is_header)
    assert tb.ev.lookup(top["module"]) is not None and tb.ev.lookup(top["module"]).kind == "module"
    a = assess_answer(f"`{top['module']}` carries {top['cells']:,} cells.", w, tb.ev)
    assert [c["as_written"] for c in a["cited"]] == [top["module"]]
    assert figures(f"`{top['module']}` carries {top['cells']:,} cells.", [json.dumps(out)])["untraced"] == []


def test_disco_letters_are_module_prefixes(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    a = assess_answer("Names such as `SYS`, `INP`, `CAL` and `SYS01`; `XYZ` and `QQ` are not.", w)
    assert a["unchecked"] == ["SYS", "INP", "CAL", "SYS01"] and a["unverified"] == ["XYZ"]


def test_a_figure_with_its_unit_in_backticks_is_a_figure(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    a = assess_answer("It took `21,900 ms`, then `5 s`; `16.0%` of effort; `CAL02 Revenue` is a module.", w)
    assert a["unverified"] == [] and a["unchecked"] == ["CAL02 Revenue"]
    f = figures("It took `21,900 ms`, then `5 s`.", ["duration_ms 21900"])
    assert f["checked"] == 1 and f["traced"] == 1 and f["untraced"] == []


def test_a_share_derives_from_the_figures_beside_it_in_a_long_answer():
    filler = " ".join(f"row {1000 + i:,}" for i in range(60))
    text = filler + "\n\n`Caldergate FP&A` holds `130,001,662 / 144,543,801 = 89.9%` of exported cells."
    f = figures(text, [" ".join(f"{1000 + i}" for i in range(60)), "cells 130001662", "total 144543801"])
    assert f["untraced"] == [] and f["derived"] == 1
