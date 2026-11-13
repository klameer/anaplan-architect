"""Write the large demo model: "Caldergate Store Planning", a fictional retail model of several thousand line items,
as a Line Items export. It exists to show one thing: a question that needs an exact count over a model far too large
to read into a prompt. Deterministic: the same file every run.

  python tools/make_store_model.py            -> examples/caldergate/stores/Line Items.csv

Shape: three system modules, then one sales-plan module per store format and category (8 formats x 24 categories),
each with the same 28 line items. A handful of patterns are planted so that counts have something to find:
  - FINDITEM on a text code, on every cell, in the Promotions line of every module of two formats
  - a hardcoded 1.2 VAT factor in every Clearance category
  - one module family (format "Outlet") that nothing reads
"""
from __future__ import annotations
import csv, json, pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "examples" / "caldergate" / "stores" / "Line Items.csv"
HEAD = ["", "Format", "Formula", "Summary", "Applies To", "Time Scale", "Time Range", "Versions", "Style", "Cell Count", "Calculation Effort", "Notes", "Referenced By", "Module Name"]
FORMATS = ["High Street", "Retail Park", "Shopping Centre", "Convenience", "Flagship", "Concession", "Online", "Outlet"]
CATEGORIES = ["Bakery", "Dairy", "Produce", "Meat", "Fish", "Frozen", "Ambient", "Confectionery", "Soft Drinks", "Beers Wines Spirits", "Household", "Health", "Beauty", "Baby",
              "Pet", "Home", "Garden", "Electrical", "Clothing", "Footwear", "Stationery", "Toys", "Seasonal", "Clearance"]
NUM = json.dumps({"dataType": "NUMBER"}); BOOL = json.dumps({"dataType": "BOOLEAN"}); TEXT = json.dumps({"dataType": "TEXT"})
SUM = json.dumps({"summaryMethod": "SUM"}); NONE = json.dumps({"summaryMethod": "NONE"}); FORMULA = json.dumps({"summaryMethod": "FORMULA"})


def rows():
    def module(name, items, dims="Stores", time="Week", cells=5200):
        yield [name, "", "", "", "", "Not Applicable", "Not Applicable", "Not Applicable", "", 0, "", "", "", ""]
        for nm, fmt, formula, summ, note, d, c in items:
            yield [nm, fmt, formula, summ, d if d is not None else dims, time if (d is None or "Week" in (d or "") or True) else "Not Applicable", "Model Calendar", "All", "", c if c is not None else cells,
                   "", note, "", name]

    yield from module("SYS01 Time Settings", [
        ("Actual?", BOOL, "", NONE, "Set by the weekly close.", "", 104),
        ("Current Week?", BOOL, "ITEM(Time) = 'SYS00 Model Settings'.Current Week", NONE, "", "", 104),
        ("Trading Weeks", NUM, "IF Actual? THEN 1 ELSE 1", SUM, "", "", 104)])
    yield from module("SYS00 Model Settings", [
        ("Current Week", json.dumps({"dataType": "TIME_ENTITY"}), "", NONE, "", "", 1),
        ("VAT Rate", NUM, "", NONE, "", "", 1),
        ("Shrink Target %", NUM, "", NONE, "", "", 1)], time="Not Applicable")
    yield from module("SYS02 Store Attributes", [
        ("Region", json.dumps({"dataType": "ENTITY"}), "", NONE, "", "Stores", 320),
        ("Open?", BOOL, "", NONE, "", "Stores", 320),
        ("Selling Area", NUM, "", SUM, "Square metres.", "Stores", 320),
        ("Store Code", TEXT, "CODE(ITEM(Stores))", NONE, "", "Stores", 320)], time="Not Applicable")
    for f in FORMATS:
        for c in CATEGORIES:
            m = f"PLN {f} {c}"
            q = lambda n: f"'{m}'.{n}"
            vat = "Gross Sales / 1.2" if c == "Clearance" else "Gross Sales / (1 + 'SYS00 Model Settings'.VAT Rate)"
            promo = (f"FINDITEM(Promotions, Promo Code)" if f in ("Online", "Flagship") else "Promo Lookup")
            items = [
                ("Base Units", NUM, "", SUM, "Entered by the category planner.", None, None),
                ("Seasonality Index", NUM, "", NONE, "", None, None),
                ("Promo Code", TEXT, "", NONE, "", None, None),
                ("Promo Lookup", NUM, "", NONE, "", None, None),
                ("Promotion", json.dumps({"dataType": "ENTITY"}) if promo.startswith("FINDITEM") else NUM, promo, NONE,
                 "Text code turned into a list item on every cell." if promo.startswith("FINDITEM") else "", None, None),
                ("Promo Uplift %", NUM, "", NONE, "", None, None),
                ("Open Store?", BOOL, "'SYS02 Store Attributes'.Open?", NONE, "", None, None),
                ("Forecast Units", NUM, "IF Open Store? THEN Base Units * Seasonality Index * (1 + Promo Uplift %) ELSE 0", SUM, "", None, None),
                ("Actual Units", NUM, "", SUM, "Loaded from the till feed.", None, None),
                ("Units", NUM, "IF 'SYS01 Time Settings'.Actual? THEN Actual Units ELSE Forecast Units", SUM, "", None, None),
                ("Price", NUM, "", NONE, "", None, None),
                ("Gross Sales", NUM, "Units * Price", SUM, "", None, None),
                ("Net Sales", NUM, vat, SUM, "VAT factor hardcoded." if c == "Clearance" else "", None, None),
                ("Unit Cost", NUM, "", NONE, "", None, None),
                ("Cost of Sales", NUM, "Units * Unit Cost", SUM, "", None, None),
                ("Shrink %", NUM, "", NONE, "", None, None),
                ("Shrink", NUM, "Cost of Sales * Shrink %", SUM, "", None, None),
                ("Shrink vs Target", NUM, "Shrink % - 'SYS00 Model Settings'.Shrink Target %", NONE, "", None, None),
                ("Margin", NUM, "Net Sales - Cost of Sales - Shrink", SUM, "", None, None),
                ("Margin %", NUM, "DIVIDE(Margin, Net Sales)", FORMULA, "", None, None),
                ("Sales per Sq M", NUM, "DIVIDE(Net Sales, 'SYS02 Store Attributes'.Selling Area)", FORMULA, "", None, None),
                ("Units Last Year", NUM, "LAG(Units, 52, 0)", SUM, "", None, None),
                ("Units Growth", NUM, "DIVIDE(Units - Units Last Year, Units Last Year)", FORMULA, "", None, None),
                ("Sales Last Year", NUM, "LAG(Net Sales, 52, 0)", SUM, "", None, None),
                ("Sales Growth", NUM, "DIVIDE(Net Sales - Sales Last Year, Sales Last Year)", FORMULA, "", None, None),
                ("Cumulative Sales", NUM, "CUMULATE(Net Sales)", NONE, "", None, None),
                ("Label", TEXT, "NAME(ITEM(Stores)) & \" / \" & \"" + c + "\"", NONE, "", None, None),
                ("Check", NUM, "Gross Sales - Net Sales - (Gross Sales - Net Sales)", SUM, "", None, None),
            ]
            yield from module(m, items, dims="Stores", time="Week", cells=320 * 104)
    # the summary every format except Outlet feeds: Outlet modules are read by nothing
    summ = []
    for f in FORMATS[:-1]:
        refs = " + ".join(f"'PLN {f} {c}'.Net Sales" for c in CATEGORIES)
        summ.append((f"{f} Net Sales", NUM, refs, SUM, "", None, None))
        refs = " + ".join(f"'PLN {f} {c}'.Margin" for c in CATEGORIES)
        summ.append((f"{f} Margin", NUM, refs, SUM, "", None, None))
    summ.append(("Total Net Sales", NUM, " + ".join(f"{f} Net Sales" for f in FORMATS[:-1]), SUM, "", None, None))
    summ.append(("Total Margin", NUM, " + ".join(f"{f} Margin" for f in FORMATS[:-1]), SUM, "", None, None))
    summ.append(("Total Margin %", NUM, "DIVIDE(Total Margin, Total Net Sales)", FORMULA, "", None, None))
    yield from module("OUT01 Store Summary", summ, dims="Stores", time="Week", cells=320 * 104)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        for r in rows():
            w.writerow(r); n += 1 if r[-1] else 0
    print(f"{OUT.relative_to(OUT.parents[3])}: {n} line items, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
