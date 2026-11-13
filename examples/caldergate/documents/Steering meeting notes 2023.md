# Planning systems steering meeting: notes, 2023

Caldergate Distribution Group. Monthly meeting, held in the last week of each month. Chair: Head of Finance Systems. Standing attendees: FP&A Manager, Group Reporting Manager, HR Analytics Lead, Group Treasury (by invitation), Dan (Finance Systems analyst). Notes taken by Finance Systems. The financial year runs April to March, so FY24 is the year to March 2024.

Models covered: Caldergate Data Hub, Caldergate FP&A, Workforce Planning and, from August, Board Reporting.

## January 2023

- FY24 budget round. All cost centre owners have submitted drivers in `INP02 Opex Drivers`. FP&A are reviewing 11 cost centres where the total moved more than 10 per cent on the prior year.
- Volume plan for FY24 agreed with the sales directors. Price assumptions still to come for two regions.
- December close: actuals load ran on working day 3 without incident. Trial balance agreed to NetSuite.
- Dan proposed a small separate model for the board KPIs, so that the board dashboard does not sit on the FP&A model. Agreed in principle. Dan to bring a one-page scope in February.
- Selective access review with Internal Audit completed. Four leavers removed.
- Action: FP&A to close the 11 cost centre queries before the February meeting.

## February 2023

- FY24 budget approved by the Board on 21 February. Finance Systems copied Forecast to the Budget version the next day and locked it.
- Board KPI model: scope accepted. Dan to build it in-house, using the same module prefixes as FP&A. Working name Board Reporting. No partner involvement.
- External audit: the auditors confirmed that the FY22 file is still open. `CAL05 Opex OLD` therefore stays in the FP&A model for now. No change request has been raised.
- HR Analytics reported that the Workday load into Workforce Planning took over 20 seconds in January. No action; it is within the window.
- Action: Dan to share the Board Reporting module list in March.

## March 2023

- Year-end roll planned for 3 April. The model calendar moves on one year. Finance Systems to load opening assets for depreciation from the Financial Controller's schedule.
- National Insurance: Finance Systems to update the threshold in `SYS00 Model Settings` in April, as every year.
- Weekend days and bank holidays for FY24 keyed in both FP&A and Workforce Planning.
- Board Reporting: module list reviewed. It will import the P&L by cost centre and the board pack lines from FP&A, and headcount by department from Workforce Planning.
- Group Reporting asked whether cost centre allocations could be added to the P&L. Not this year.
- Action: Finance Systems to confirm the roll checklist with FP&A by 31 March.

## April 2023

- Roll completed on 3 April. Opening cash balances entered by Treasury on 5 April.
- Corporation tax. The main rate rose to 25 per cent on 1 April. The rate in CAL08 Cash Flow.Tax was changed from 0.19 to 0.25 in the formula itself because the tax estimate has always had its rate written into the formula, and Finance Systems did not want to redesign the line during the year-end roll. Finance Systems noted that it should read `SYS00 Model Settings.Corporation Tax Rate` and that the override in `INP05 Balance Sheet Drivers` has never been wired in. Not prioritised.
- Workforce rates. HR Analytics have keyed the NI and pension rates into Inputs - Settings by hand since August 2022, and no longer run Import from Caldergate FP&A - Assumptions, because the FP&A export carries no pension rate and they would rather key three numbers once a year than run an import and then correct it. The import action has been left in Workforce Planning.
- FP&A asked for the phased drivers on the management pack to be reordered. Agreed.
- Action: none carried.

## May 2023

- April close: actuals load on working day 3. One new cost centre arrived in the ledger before the master data refresh; reloaded the next day.
- Board Reporting: build about half done. Dan demonstrated the KPI module. Revenue per FTE needs headcount by department from Workforce Planning; HR Analytics agreed to add an export.
- Workday. It was noted that the Data Hub and Workforce Planning each load employees from Workday. HR Analytics explained that salaries are not allowed in the hub. Accepted as is; the two employee lists are not reconciled to each other.
- Budget template for FY25 to be reissued in the autumn with two new drivers requested by Property.
- Action: HR Analytics to build the department headcount export by June.

## June 2023

- Product master. Marketing supplied a PIM extract on 14 June and told Finance Systems it would be the last from the current team. The product master will fall out of date from this month because the Marketing restructure removed the post that prepared the PIM file, and nobody in Marketing or Finance Systems has agreed to own it. The import in the Data Hub is manual and stays as it is. New products will not appear in `DAT04 Product Master` or in the FP&A product list until someone supplies a file.
- The Head of Finance Systems to raise ownership with the Marketing Director. Finance Systems will not maintain product data by hand.
- May close: no issues.
- Board Reporting: user testing with the CFO's office booked for July.
- Trading: the CFO has asked FP&A to assess the effect of the lost national account on the second half.
- Action: Head of Finance Systems to write to the Marketing Director about the PIM file.

## July 2023

- Mid-year re-cut. The CFO has asked for a re-cut of the FY24 budget following the loss of the national account. Finance Systems created a fourth version, Budget v2, on 12 July and copied the current forecast into it as the starting point.
- Finance Systems reminded the meeting that a fourth version adds about a third to every versioned module, and asked that it be removed if it is not adopted.
- PIM file: no reply from Marketing.
- Board Reporting: user testing done. Two layout changes requested.
- June close: the actuals load was delayed a day by a late ledger close.
- Action: FP&A to complete the re-cut by the end of August.

## August 2023

- Board Reporting went live on 14 August. Its process Refresh Pack is run by Dan after FP&A's Roll Forecast, never before it.
- Re-cut: drivers revised for 38 cost centres. Volumes revised for three regions. FP&A on track.
- The CFO's office asked for the September board pack to show the original budget and the re-cut side by side. Dan to add a line to `OUT02 Board Pack` that selects Budget v2.
- PIM file: the Marketing Director replied that Marketing has no one to do it. Still no owner.
- Holiday cover for the monthly load agreed.
- Action: Dan to add the board pack line before the September pack.

## September 2023

- Re-cut presented to the Board on 19 September as the Q3 restatement. The Board asked for more work on the cost savings and deferred its decision to October.
- The September board pack showed both budgets, as requested.
- Product master: three products launched since June are missing from the Data Hub. FP&A are planning them against an existing product for now.
- Workforce Planning: HR Analytics asked whether attrition could be shown by department. Parked.
- August close: no issues.
- Action: FP&A to rework the savings schedule for the October Board.

## October 2023

- Budget v2. The Board did not approve the mid-year re-cut at its meeting on 17 October, so the original Budget version stands and Finance Systems has renamed the re-cut version Budget v2 DO NOT USE. Reporting for the rest of FY24 is against the original budget.
- The line Dan added in August has been renamed and kept. OUT02 Board Pack.Old Budget Revenue still selects Budget v2 DO NOT USE because the September and October board packs showed the re-cut beside the original budget, and the Board may ask for those comparatives again. Dan asked to be consulted before the line or the version is removed.
- Finance Systems repeated that the version should be deleted once the comparatives are no longer needed. No date set.
- The Board has asked for group revenue in US dollars, for the new lender's quarterly pack. Dan to build a `Revenue USD` line in `CAL02 Revenue`, reading the dollar rate in `SYS05 FX Rates`.
- September close: no issues.
- Action: Dan to have the dollar line ready for the November pack.

## November 2023

- FX file. Group Treasury has stopped producing the monthly FX file now that its rates are held in the new treasury management system, so Import FX from Treasury file was run for the last time on 2 November 2023. Treasury has no plan to produce a file in the old layout. The rates in `SYS05 FX Rates` stay at the last loaded values until something replaces the file.
- Revenue in US dollars. CAL02 Revenue.Revenue USD will keep a fixed rate of 1.27 written into the formula as a stop-gap, because no new rates are being loaded into SYS05 FX Rates and the Board needs the dollar figure before a rate feed can be built. The line was built in October to read the rates module and was changed before release. This is against the design record, which says no rate is to be written into a formula, and the meeting accepted it as temporary.
- Finance Systems proposed taking rates from the treasury management system through the Data Hub. Treasury supportive. No budget this year.
- PIM file: no change.
- October close: no issues.
- Action: Treasury to confirm the dollar planning rate. Finance Systems to scope a rate feed for the FY25 change list.

## December 2023

- Dollar rate: Treasury will confirm the planning rate of 1.27 in January. It is to be reviewed whenever Treasury changes its planning rate, and until then stays as it is.
- Rate feed: on the FY25 change list, unfunded.
- FY25 budget round opened. Template issued to cost centre owners on 4 December with the two new Property drivers.
- Budget v2 DO NOT USE: still in the model. Dan confirmed that the January pack may be asked for the comparatives.
- PIM file: no owner. Seven products now missing.
- November close: actuals load on working day 3. Trial balance agreed.
- Selective access review with Internal Audit completed. Two movers corrected.
- Next meeting: last week of January 2024.
