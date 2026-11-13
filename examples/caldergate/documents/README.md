# Caldergate project documents (fictional)

Example project documents for the Caldergate Distribution Group demo estate. Caldergate, its staff and its partners are invented. Each document gives the reason behind a quirk planted in the demo models (the numbers below are the rows of `PLANTED.md` in anaplan-estate's `examples/caldergate-estate`). Upload them to a workspace that holds the Caldergate estate, then ask the test questions. The answer sentence is copied word for word from the document.

Source of truth: the Caldergate dataset kept with the CodelessOps shared assets. This folder is a copy.

## The documents

| Document | What it is | Planted quirks it explains |
|---|---|---|
| `FPA design decision record v1.2.md` | The first partner's design record for Caldergate FP&A: first issued March 2019, revised June 2020 and February 2021. 25 numbered sections, most of them ordinary design content | 2, 3, 4, 5 (VAT, pension), 8, 9, 10, 11, 12 (Launched?), 13 and 14 (FP&A), 15 and 31 (Revenue Label), 16, 21 (why the FX import is manual), 25 |
| `Steering meeting notes 2023.md` | Monthly steering notes, January to December 2023 | 5 (1.27 USD rate, 0.25 tax), 18, 21 (when and why the file stopped), 22, 23, 32 (Old Budget Revenue); the stale product master |
| `Partner handover note 2021.md` | The second partner's handover of Workforce Planning | 5 (bonus), 12 (Leavers), 13 (Employee Name), 20, 22, 23, 26, 31 (NI Rate, Bonus %), 32 (zz Archive, Hub v1); the two naming conventions |
| `CR-031 Legal fees driver.md` | Change request, May 2024, status open | 3 (the thirteenth branch) |
| `CR-044 Retire CAL05 Opex OLD.md` | Change request, February 2025, decision deferred | 1, 32 (the OLD module) |
| `netsuite_gl_load.py` | The integration script behind the Data Hub's Daily Load. Never executed here | The Data Hub's daily GL load and its `Source System` text line item |

## Test questions, one per document

**1. `FPA design decision record v1.2.md`, section 4.3**
Question: Why is the account-to-driver mapping written into the Forecast Opex formula instead of a mapping table?
Answer sentence: "The account-to-driver mapping is written into the IF chain of CAL03 Opex.Forecast Opex because Finance Systems did not want planners, or anyone outside Finance Systems, to be able to edit a mapping table, and a change to the mapping is therefore a model change that goes through Finance Systems."

**2. `Steering meeting notes 2023.md`, November 2023**
Question: Why does Revenue USD use a hardcoded 1.27?
Answer sentence: "CAL02 Revenue.Revenue USD will keep a fixed rate of 1.27 written into the formula as a stop-gap, because no new rates are being loaded into SYS05 FX Rates and the Board needs the dollar figure before a rate feed can be built."

**3. `Partner handover note 2021.md`, section 6**
Question: Why are NI Threshold and NI Rate in INP03 Headcount and not only in the settings module?
Answer sentence: "We added INP03 Headcount.NI Threshold and INP03 Headcount.NI Rate to INP03 Headcount, next to the salaries, because we wanted the threshold and the rate visible on the same grid as the salaries they are applied to when the imported figures are checked each month."

**4. `CR-031 Legal fees driver.md`, Reason**
Question: Why does Forecast Opex need a thirteenth branch?
Answer sentence: "A thirteenth branch is needed in CAL03 Opex.Forecast Opex because the legal fees account has no branch in the formula, so its forecast is zero even though cost centre owners enter a Legal Fees driver in INP02 Opex Drivers."

**5. `CR-044 Retire CAL05 Opex OLD.md`, Why it is still there**
Question: Why is CAL05 Opex OLD still in the model if nothing reads it?
Answer sentence: "CAL05 Opex OLD has been kept since it was replaced because the external auditors' working papers for FY22 reference its numbers, and the FY22 audit file has not been closed."

**6. `netsuite_gl_load.py`, module docstring**
Question: Why is Source System loaded as text on every GL row in the Data Hub?
Answer sentence: "Source System is loaded as text on
every row because the ledger receives journals from NetSuite itself and from
the warehouse billing interface, and Group Reporting asked to see which system
a balance came from when the hub's data check reports a difference."
(The sentence runs over four lines of the docstring; the line breaks are as in the file.)

## Further questions on the large document

These test that only the relevant section is pulled from the design record.

**7. Section 4.9**
Question: Why is the depreciation Charge formula so long?
Answer sentence: "CAL10 Depreciation.Charge is long because it has one branch per asset class, each with its own useful life, and it is written that way so that the charge reconciles to the fixed asset register class by class."

**8. Section 5.1**
Question: Why do the pack lines keep Versions when their formulas do not need them?
Answer sentence: "Line items in OUT01 Management Pack and OUT02 Board Pack keep Versions, even where a line's formula does not need them, because the board compares Actual, Forecast and Budget side by side on the pack views."

**9. Section 4.5**
Question: Why is the FX import run by hand, outside any process?
Answer sentence: "Import FX from Treasury file is run by hand and sits outside every process because the Treasury file is sometimes late and the monthly actuals load must not wait for it."

## Further questions on the other documents

**10. `Steering meeting notes 2023.md`, October 2023**
Question: Why is there a version called Budget v2 DO NOT USE?
Answer sentence: "The Board did not approve the mid-year re-cut at its meeting on 17 October, so the original Budget version stands and Finance Systems has renamed the re-cut version Budget v2 DO NOT USE."

**11. `Steering meeting notes 2023.md`, June 2023**
Question: Why is the product master out of date?
Answer sentence: "The product master will fall out of date from this month because the Marketing restructure removed the post that prepared the PIM file, and nobody in Marketing or Finance Systems has agreed to own it."

**12. `Steering meeting notes 2023.md`, November 2023**
Question: Why did the Treasury FX file stop?
Answer sentence: "Group Treasury has stopped producing the monthly FX file now that its rates are held in the new treasury management system, so Import FX from Treasury file was run for the last time on 2 November 2023."

**13. `Partner handover note 2021.md`, section 7**
Question: Why is there still an import from Caldergate Hub v1?
Answer sentence: "Import from Caldergate Hub v1 - Cost Centres was left behind because the old hub was switched off in March 2021 before the first partner had deleted the action, the first partner's support ended soon after, and we were asked not to delete anything in FP&A that we had not built."

## Questions no document answers

The tool should answer these as not recorded. No document and no owner note gives the reason.

- Why is the margin module named `CAL04 Margn`? (The documents use the name and never comment on the spelling.)
- Why does `CAL12 Driver Phasing.Insurance Phased` read `Current Period?` when every other phased line reads `Actual?`? (The design record says each phased line is zero in actual months; it does not mention an exception.)

Also not explained by any document: why `CAL07 P&L by Cost Centre.EBITDA Margin` is summed (29), the `Benchmark Opex` temporary fix from the Q3 FY25 close (7, covered by an owner note only), and DIVIDE() beside a plain division (6).
