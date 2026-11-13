# CR-044: Retire CAL05 Opex OLD

| | |
|---|---|
| Change request | CR-044 |
| Model | Caldergate FP&A |
| Raised by | Finance Systems |
| Date raised | 11 February 2025 |
| Owner | Finance Systems |
| Status | Deferred |

## Request

Delete the module `CAL05 Opex OLD` from Caldergate FP&A.

## Background

`CAL05 Opex OLD` is the original 2019 opex module. It has a separate forecast line item for each driver account and a line that adds them up. It was replaced by `CAL03 Opex` in 2021, when the driver-based forecast moved to a single formula. The old module was renamed and kept for the parallel run. The parallel run was signed off in 2021 and the module was never removed.

The module has 14 calculated line items, each by cost centre, account, month and version, which is about five million cells each. No formula in the model reads any of them and no export is defined on the module. Finance Systems have not been able to confirm from the model alone whether a saved view or a page still shows it.

## Why it is still there

CAL05 Opex OLD has been kept since it was replaced because the external auditors' working papers for FY22 reference its numbers, and the FY22 audit file has not been closed. The FY22 budget and the first-quarter forecast for that year were produced from the old module before `CAL03 Opex` went live, and the budget-to-actual opex analysis given to the auditors was exported from it. The file remains open while a query on the FY22 dilapidations provision is unresolved. The Group Reporting Manager has asked that the module stays available in the live model until the auditors confirm the file is closed, so that any figure in the working papers can be shown in the system it came from.

## Why Finance Systems want it removed

- It holds about 70 million cells that nothing uses.
- It accounts for roughly half of the model's measured calculation effort. Every actuals load and every change to the forecast start month recalculates it.
- It still reads `INP02 Opex Drivers`, `DAT01 Actuals GL`, `SYS01 Time Settings` and `SYS05 FX Rates`, so it appears as a dependent whenever one of those is changed and has to be considered in every impact check.
- Its name tells a new builder it is dead, and its numbers no longer agree with `CAL03 Opex` because its forecast total leaves out two of its own driver lines.

## Options

1. Delete it now. Keep the FY22 figures as an export filed with Group Reporting.
2. Delete it now, after taking an archive copy of the model for the auditors.
3. Keep it until the FY22 audit file is closed, then delete it.

Finance Systems recommend option 2. Group Reporting prefer option 3, on the grounds that the auditors were told the figures would remain in the live model.

## Checks before deletion, whichever option is taken

- Confirm that no page and no saved view shows the module.
- Confirm that no export or import action references it.
- Record the model's size and the duration of the monthly actuals load before and after.

## Decision

The decision to retire CAL05 Opex OLD was deferred at the steering meeting of 25 February 2025 until the external auditors confirm that the FY22 audit file is closed, at which point the module can be deleted without a further change request. Group Reporting are to ask the auditors for a date. Until then the cells and the calculation time are accepted as the cost of keeping it. Nothing is to be built on the module in the meantime.

## Decision log

| Date | Note |
|---|---|
| 11 February 2025 | Raised. |
| 25 February 2025 | Steering meeting: deferred pending closure of the FY22 audit file. Option 3 stands for now. |
