# CR-031: Legal fees driver in the opex forecast

| | |
|---|---|
| Change request | CR-031 |
| Model | Caldergate FP&A |
| Raised by | FP&A Manager |
| Date raised | 14 May 2024 |
| Owner | Finance Systems |
| Status | Open |

## Request

Add a thirteenth branch to `CAL03 Opex.Forecast Opex` so that the legal fees account forecasts from the `Legal Fees` driver in `INP02 Opex Drivers`.

## Reason

Finance split legal fees out of professional fees in the chart of accounts in April 2024, after the General Counsel asked for legal spend to be reported on its own line. Actuals now post to the new account. The forecast does not follow.

A thirteenth branch is needed in CAL03 Opex.Forecast Opex because the legal fees account has no branch in the formula, so its forecast is zero even though cost centre owners enter a Legal Fees driver in INP02 Opex Drivers. Until the branch is added, FP&A are asking owners to include legal fees in the `Consultancy` driver, which forecasts to professional fees, and are moving the amount by hand in the pack commentary.

## Proposed change

1. Add one branch to the IF chain in `CAL03 Opex.Forecast Opex`, mapping the legal fees account to `INP02 Opex Drivers.Legal Fees`, placed after the audit branch.
2. Update the line item note to say thirteen branches.
3. Repeat the opex reconciliation test for three cost centres that carry legal spend.

Estimated effort: half a day including testing. The formula is by cost centre and account, so the change recalculates one of the largest line items in the model and should be released outside the close.

## Wider point: the mapping

The design record explains why the account-to-driver mapping is in the formula and not in a table. It also says the decision should be revisited as the chain grows. Finance Systems and FP&A discussed this on 21 May 2024.

Moving the mapping out of the formula into a small lookup module by account, with write access limited to Finance Systems, is agreed in principle but is out of scope for CR-031, because it changes how every driver account forecasts and needs a full reconciliation that nobody has time for before the FY25 half-year. It will be raised as a separate change request when it can be resourced. CR-031 is the minimum change that makes legal fees forecast correctly.

## Risks

- A mistake in the chain affects every driver account, not just legal fees. The reconciliation test covers this.
- The `Consultancy` driver will be overstated for any cost centre whose owner has already added legal fees to it. FP&A will ask owners to move the amount once the branch is live.

## Decision log

| Date | Note |
|---|---|
| 14 May 2024 | Raised. |
| 21 May 2024 | Reviewed by Finance Systems and FP&A. Branch approved in principle. Lookup module agreed in principle, out of scope. |
| 28 May 2024 | Steering meeting: not scheduled. Finance Systems have no build time before the half-year. Status stays open. |
