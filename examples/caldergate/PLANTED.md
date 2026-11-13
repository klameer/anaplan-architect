# The Caldergate estate: what was planted, and where the report finds it

Caldergate Distribution Group is fictional. The four models are built to
look inherited, not clean: two consultancies, three build years, naming
conventions that do not agree, a leftover module, a formula nobody dares
touch, and an import from a hub that no longer exists. Anyone who has
taken over an Anaplan estate will recognise the shape.

Everything below was put in deliberately. Run the report: the first
priority investigation should be the leftover module, and each row
below should appear as a finding or inside one's evidence. Then
run it on yours.

```
anaplan-estate examples/caldergate-estate --out estate.md
```

## The estate

| Model | Built | Naming | Line items | What it is |
|---|---|---|---|---|
| 1 Caldergate Data Hub | 2019, first partner | DAT/SYS/CAL | 63 | Loads NetSuite, Salesforce, Workday; feeds the spokes |
| 2 Caldergate FP&A | 2019, first partner | SYS/INP/DAT/CAL/OUT (DISCO) | 278 | Revenue, opex, headcount cost, cash, board pack |
| 3 Workforce Planning | 2021, second partner | "Data -", "Inputs -", "Calcs -", "Reports -" | 55 | Employee-level cost, exported to FP&A |
| 4 Board Reporting | 2023, in-house | SYS/DAT/CAL/OUT | 30 | KPIs and the board dashboard |

## Planted, by rule

| # | What | Where | Rule or section |
|---|---|---|---|
| 1 | A leftover module: 14 calculated line items, 5M cells each, no formula or export reads them. Replaced in 2021, kept "until the FY22 audit is closed". It carries about half the model's measured calculation effort. The report calls this "no consumer detected" and lists the page and view checks, never "unused" | FP&A `CAL05 Opex OLD` | Usage and retirement investigations; G-UNUSED |
| 2 | A module with 58 line items | FP&A `INP02 Opex Drivers` | A-LI-COUNT |
| 3 | A 12-branch IF that maps drivers to accounts, with a note asking for a 13th | FP&A `CAL03 Opex.Forecast Opex` | A-IF-COUNT |
| 4 | The formula nobody touches: six-branch depreciation with MOVINGSUM, 400 characters, correct | FP&A `CAL10 Depreciation.Charge` | F-LONG |
| 5 | Hard-coded assumptions: 1.27 USD rate, 0.2 VAT, 0.25 tax, 0.05 pension, 0.1 bonus | FP&A `CAL02 Revenue`, `CAL08 Cash Flow`, `INP03 Headcount`; Workforce `Calcs - Cost` | F-HARDCODE |
| 6 | DIVIDE() next to a plain / in the same module. Anaplan: / returns zero on a zero divisor, DIVIDE() returns Infinity. Neither is a fault; the report lists DIVIDE() so the owner can confirm the intended display | FP&A `CAL02 Revenue.Average Price`, `CAL04 Margn.Margin %`; Workforce `Calcs - Headcount by CC.Average Salary` | F-DIVIDE-FN (info) |
| 7 | SUM and LOOKUP in one formula (Anaplan: never use SUM and LOOKUP in the same formula), with the note "temp fix for Q3 close, remove later" | FP&A `CAL06 Department Summary.Benchmark Opex` | F-MIXED-CLAUSE |
| 8 | Four-step pass-through chains: CAL07 to CAL11 to OUT01 to OUT02 | FP&A `OUT02 Board Pack.Revenue` and three more | A-DAISY |
| 9 | Opening cash from last month's closing cash (the normal balance pattern, reported as info) | FP&A `CAL08 Cash Flow` | G-CYCLE |
| 10 | One flag every calculation reads: 35 direct dependents | FP&A `SYS01 Time Settings.Actual?` | G-HUB; Most depended-on line items |
| 11 | An empty module | FP&A `CAL09 Scenario Planning` | G-EMPTY-MODULE |
| 12 | Subsidiary views used in calculation | FP&A `CAL01 Volumes.Launched?`; Workforce `Calcs - Attrition.Leavers` | A-SUBSIDIARY |
| 13 | Text line items with millions of cells: the journal reference on every GL cell, the employee name on every month | FP&A `DAT01 Actuals GL.Source Journal`; Workforce `Data - Employees.Employee Name` | A-TEXT-FORMAT |
| 14 | FINDITEM on a 5M-cell line item | FP&A `DAT01 Actuals GL.Journal Cost Centre` | A-FINDITEM |
| 15 | Text joins and ITEM()/NAME() in large multi-dimensional line items | FP&A `CAL02 Revenue.Revenue Label`, `CAL05 Opex OLD` | A-TEXT-JOIN, A-SYSTEMS-FN |
| 16 | Summaries left on for line items no formula reads | Every model, mostly OUT modules | A-SUMMARY-ON |
| 17 | Modules with no notes: most of them | Every model | H-NOTES |
| 18 | A version called "Budget v2 DO NOT USE", still selected by a board pack line, with a note saying to ask Dan before removing it | FP&A `OUT02 Board Pack.Old Budget Revenue` | F-SELECT-TIME (hard-coded version selection) |
| 19 | A module name with a typo nobody fixed because renaming breaks the views | FP&A `CAL04 Margn` | Read the module list |
| 29 | A percentage left on the default summary: EBITDA margin is summed, so the all-cost-centres total adds up the percentages | FP&A `CAL07 P&L by Cost Centre.EBITDA Margin` | F-RATIO-SUM (test 4.16) |
| 30 | Thirty phased drivers pasted from one formula; one reads `Current Period?` where the other twenty-nine read `Actual?` | FP&A `CAL12 Driver Phasing.Insurance Phased` | F-ODD-ONE (test 4.17) |
| 31 | Rates and thresholds held on every cost centre, role, month and version when they are one number; text labels held on every month and version | FP&A `INP03 Headcount.NI Rate`, `CAL02 Revenue.Revenue Label`; Workforce `Calcs - Cost.NI Rate`, `Calcs - Headcount by CC.Bonus %` | G-OVERDIM (test 1.7) |
| 32 | Names that say leftover: the OLD module, the `zz Archive` module, the "Old Budget Revenue" line still selecting "Budget v2 DO NOT USE", the Hub v1 import | FP&A `CAL05 Opex OLD`, `OUT02 Board Pack.Old Budget Revenue`; Workforce `zz Archive - 2021 Cost` | H-LEFTOVER (test 2.5) |

## Planted, in the actions

| # | What | Where | Report section |
|---|---|---|---|
| 20 | An import from a hub that no longer exists, last run March 2021, in no process. It loads the same module as the import that replaced it | FP&A `Import from Caldergate Hub v1 - Cost Centres` | External sources ("Caldergate Hub v1"); stale; orphan; several imports loading one target (test 5.4) |
| 21 | A manual FX upload last run November 2023, in no process | FP&A `Import FX from Treasury file` | Stale; orphan |
| 22 | Rates once imported from FP&A, now "keyed by hand"; the import survives | Workforce `Import from Caldergate FP&A - Assumptions` | Stale; orphan; still counted as a feed FP&A to Workforce |
| 23 | Two models load Workday independently | Data Hub `Import Employees from Workday`; Workforce `Import Employees from Workday` | External sources: Workday, 2 imports |
| 24 | Exports nobody scheduled | Every model | Imports not in any process |

## Planted, across models

| # | What | Where | Report section |
|---|---|---|---|
| 25 | The same account flags and time flags rebuilt in the hub and the spoke | `Revenue?`, `Opex?`, `COGS?`, `Sign`, `Group`, `Current Period?` in Data Hub and FP&A | Logic duplicated across models |
| 26 | The same NI and working-days formulas written by two different partners | `Employer NI`, `Working Days` in FP&A and Workforce | Logic duplicated across models |
| 27 | The feed graph: Hub feeds FP&A and Workforce; Workforce feeds FP&A; FP&A and Workforce feed Board Reporting; and one stale feed FP&A to Workforce | Import action names | How the models connect |
| 28 | Workforce Planning was exported before Calculation Effort existed, so that chapter says so | Workforce | Where the calculation time goes |

Rows 29 to 32 were added with the numbered test list
([docs/TESTS.md](../../docs/TESTS.md)); the report's *Tests run* table
shows every test and what it found here.

## What is not planted

- Referenced By is computed from the parsed formulas, so the agreement
  check reads 100 percent on every model. On a real export the column is
  Anaplan's, and the agreement number is the honest measure of how far
  to trust the graph.
- Cell counts are dimension sizes multiplied out. Real exports count
  summary cells too, so real numbers run higher.
- No page, dashboard or saved view exists. Line items the report calls
  unreferenced may, in a real estate, be read by a page; the exports
  cannot tell.

Rebuild the estate with `python examples/build_caldergate_estate.py`.
