# Caldergate FP&A: design decision record v1.2

Prepared by the implementation partner for Finance Systems, Caldergate Distribution Group.

| Version | Date | Change |
|---|---|---|
| v1.0 | March 2019 | First issue, at the end of the design phase |
| v1.1 | June 2020 | Depreciation added (section 4.9); capex input added to scope |
| v1.2 | February 2021 | Opex forecast logic revised for the single driver formula (sections 4.3 and 4.4); hub move noted (section 3.1); open items refreshed |

Status: approved by the Head of Finance Systems. Distribution: Finance Systems, FP&A, Group Reporting, Internal Audit.

This record states what was decided and why. It is not a build specification and it is not a user guide. Where a decision is recorded, the reason is given in the same section, so that a later model builder can judge whether the reason still holds before changing the design.

## 1.1 Purpose and status of this record

Caldergate Distribution Group replaced its spreadsheet budget and forecast with an Anaplan model, Caldergate FP&A, during the financial year ending March 2019. The spreadsheet process relied on one workbook per cost centre, consolidated by hand by the FP&A team over roughly eight working days each quarter. The steering group asked for a single model that the cost centre owners plan in directly and that produces the management pack and the board pack from the same numbers.

This document records the design decisions taken in the workshops held between January and March 2019, and the two later revisions listed in the table above. Each section covers one area of the model. The modules are named as they are in the model, and a line item is written as Module.Line Item where a decision concerns it.

A decision in this record is binding on the build team. A change to a decision is made by reissuing the record, not by a note in the model. Where the model and this record disagree, the model is what runs and the record is out of date; Finance Systems should then correct the record. The implementation partner's support arrangement ends in mid 2021, after which Finance Systems owns this document.

The record is deliberately written in plain terms for finance readers. Formula text is not reproduced here except where the shape of a formula is itself the decision.

## 1.2 Scope

In scope for the FP&A model:

- Sales volumes and revenue by product and region, monthly.
- Cost of goods and gross margin by product and region.
- Operating expenses by cost centre and account, with actuals from the general ledger and a driver-based forecast.
- Headcount cost by cost centre and role.
- A profit and loss account by cost centre, summarised by department and by legal entity.
- Capital expenditure and depreciation by cost centre (added in v1.1).
- A simple indirect cash flow by legal entity.
- The monthly management pack and the board pack.

Out of scope, by decision of the steering group in February 2019:

- A full balance sheet. The cash flow uses a small number of working capital drivers and does not attempt to balance.
- Statutory consolidation and intercompany elimination, which stay in the consolidation tool owned by Group Reporting.
- Employee-level workforce planning. In phase 1 headcount is planned by cost centre and role. A separate workforce model is being built by another partner during 2021 and that partner will document its feed into this model.
- Scenario planning. See section 7.1.
- Customer-level revenue planning. Customers exist in the data hub for order actuals but the plan is by product and region.

The model serves about 90 planners (the cost centre owners and their delegates), six FP&A analysts and a small number of read-only executives. It is not a transactional system and holds no data that is not also held in a source system or entered as a planning assumption.

## 2.1 Naming convention

Modules are named by function, using the five prefixes below and a two-digit number. The convention is the common one for Anaplan models and was chosen so that any later builder would recognise it.

| Prefix | Meaning | Rule |
|---|---|---|
| SYS | System | Settings, time flags and list attributes. No user input except by Finance Systems. |
| INP | Input | Where planners or analysts type. No calculation beyond simple totals and checks. |
| DAT | Data | Loaded from the data hub. Never typed into. |
| CAL | Calculation | Logic only. No input, no pages built directly on it. |
| OUT | Output | What pages and exports read. No logic beyond year to date and variance lines. |

The number orders modules within a prefix in roughly the order the calculation flows, so `CAL01 Volumes` comes before `CAL02 Revenue`. Numbers are not reused. When a module is retired its number is left vacant, so that old documentation and old exports never point at a different module of the same number.

Line items are named in plain business words with no prefixes. Boolean line items end in a question mark, for example `Actual?` and `Launched?`. Line items that hold a list member are named after the list in the singular. Abbreviations are avoided except CC for cost centre, FTE and GBP.

Actions are named by what they do and where the data comes from, for example "Import from Caldergate Data Hub - GL Actuals". An import from another Anaplan model always starts "Import from" followed by the source model name, so that the feeds between models can be read from the action list alone.

Notes are expected on any line item whose formula a new builder would not understand on first reading. In practice the notes column has been filled in unevenly, and that is listed in section 7.1.

## 2.2 Lists and hierarchies

The model has the following main lists.

| List | Top level | Source | Approximate size |
|---|---|---|---|
| Cost Centres | Group, then cost centre | NetSuite, through the data hub | 133 including group totals |
| Accounts | Flat, grouped by attribute | NetSuite, through the data hub | 262 |
| Products | Flat, grouped by attribute | Product master file, through the data hub | about 400 |
| Regions | Flat | Maintained by Finance Systems | 8 |
| Departments | Flat | Maintained by Finance Systems | 14 |
| Legal Entities | Flat | Maintained by Finance Systems | 5 |
| Roles | Flat | Maintained by Finance Systems | 12 |
| Currencies | Flat | Maintained by Finance Systems | 4 |

Cost Centres is the only list with a real hierarchy. The parent of each cost centre is its group, which exists for summary on pages. Department, region and legal entity are attributes of the cost centre held in `SYS02 Cost Centre Attributes`, not levels of the hierarchy. The reason is that Caldergate reorganises departments more often than it changes cost centres, and an attribute can be changed by an import without rebuilding a hierarchy or losing data at the old parent.

Accounts are flat for the same reason. The chart of accounts in NetSuite has reporting groups that Group Reporting changes for statutory purposes. The planning model needs only the account type and the P&L line, both held in `SYS03 Account Attributes`.

List members are loaded with a code, taken from the source system. Every import maps on code, never on name, so a renamed cost centre or account does not create a duplicate.

Numbered lists are not used. There was no transactional data in scope that required them.

## 2.3 Time and the actuals flag

The model calendar runs April to March, matching the financial year. The timescale is months. The model holds three financial years: the prior year, the current year and the next year, which is 36 months. Quarter and year totals are switched on. Half-year totals are not.

Weeks were considered for the volume plan and rejected. The sales team plans promotions by week, but the finance plan is monthly, and a weekly timescale would have multiplied the largest modules by more than four for the benefit of one input page.

The current period and the first forecast month are held in `SYS00 Model Settings` as `Current Period` and `Forecast Start`. Finance Systems changes them once a month as part of the roll forward. No formula anywhere in the model names a month.

`SYS01 Time Settings` turns those two settings into flags by month. SYS01 Time Settings.Actual? is the single switch between actuals and forecast, and every calculation module reads it so that rolling the forecast forward is one change to SYS00 Model Settings.Forecast Start. This was a deliberate decision. The alternative, a switchover on the Forecast version, was rejected because the same logic had to serve the Budget version, where there is no switchover, and because the planners needed to see on the page which months were actual.

The consequence is that `Actual?` has a large number of dependents and any change to it recalculates most of the model. That is accepted. It should never be given a more complicated formula than the comparison it has today.

`SYS01 Time Settings` also holds the working days calculation, from days in the month less weekend days and bank holidays, which Finance Systems keys once a year. Working days were intended for phasing certain costs and are used less than was expected.

## 2.4 Versions

Three versions were created at go-live: Actual, Forecast and Budget.

Actual holds loaded actuals only. Forecast holds actuals for closed months and the plan for open months. Budget is the approved budget for the year, frozen by Finance Systems once the board has approved it. The budget is produced in the Forecast version during the budget round and copied to Budget when it is signed off.

Native versions were chosen over a custom Versions list because the model needed version comparison on pages from day one and because bulk copy between versions is the simplest way to freeze a budget. The known drawbacks were accepted: every module that carries Versions carries all of them, and a formula that needs one version by name has to select it.

A formula that selects a version by name is allowed only in the output modules and in variance lines. `CAL07 P&L by Cost Centre` has one such line for the opex budget. The rule exists because a version named in a formula stops that version from being deleted or renamed freely.

New versions are created only by Finance Systems, and only for a number that the business will report against. Working copies of a forecast are made by copying the model, not by adding a version. Each version added to this model adds roughly a third to the size of every versioned module, so a version that is no longer reported against should be removed in the same year.

System and attribute modules do not carry Versions. An exchange rate is the exception: `SYS05 FX Rates` carries Versions so that the budget can be held at budget rates.

## 3.1 Data hub feeds

All source data reaches this model through the data hub. The FP&A model has no direct connection to NetSuite, Salesforce or any other source system. The single exception is the exchange rate file described in section 4.5.

The hub loads the general ledger, cost centres and accounts from NetSuite, sales orders, pipeline and customers from Salesforce, and the product master from a file supplied by Marketing. Its integration script is kept with the hub's own documentation.

This model imports five things from the hub:

| Import | Target | Frequency |
|---|---|---|
| GL actuals | `DAT01 Actuals GL` | Monthly, after the ledger closes |
| Volumes | `DAT02 Actuals Volumes` | Monthly, with the GL |
| Cost centres | `SYS02 Cost Centre Attributes` and the list | Monthly, on the 1st |
| Products | `SYS04 Product Attributes` and the list | Monthly, on the 1st |
| Accounts | `SYS03 Account Attributes` and the list | Monthly, on the 1st |

The hub loads the ledger daily, but this model takes actuals monthly. The planners asked not to see a part-finished month, and Group Reporting did not want an unreconciled ledger in a board number.

Volumes are imported from the hub's summary module and not from the raw sales orders. The hub sums orders from customer to region, so the spoke never holds customer-level data and its volume modules stay at product by region.

The hub in use at go-live is the model now referred to as Caldergate Hub v1. It is being rebuilt in the production workspace as Caldergate Data Hub, with the same structure, and the feeds into this model are being moved across one at a time. The cost centre feed is the last, planned for March 2021. Each old import is to be deleted once its replacement has run for one close.

## 3.2 Actuals in the spoke

`DAT01 Actuals GL` holds the ledger by cost centre, account and month. It is the largest loaded module in the model and one of the two largest overall.

Three decisions were taken about it.

First, the amount is loaded in local currency with the ledger's own sign. Sign and currency conversion are applied in the calculation modules. This keeps the loaded figure equal to the NetSuite trial balance, which is the test Group Reporting applies after every load.

Second, a journal reference is held next to the amount. DAT01 Actuals GL.Source Journal holds the journal reference as text on every cost centre, account and month because Group Reporting asked to be able to trace an unexpected actual back to NetSuite without leaving Anaplan. Where several journals post to one cell, the reference of the largest is loaded. The cost of a text line item at this size was explained in the workshop and accepted. If the model's size becomes a problem, this is the first line item to reconsider, since the same trace can be done in NetSuite with the cost centre, account and period.

Third, recharges are traced. DAT01 Actuals GL.Journal Cost Centre uses FINDITEM on the journal reference because intercompany recharge journals are referenced by the code of the cost centre that raised them, and FP&A wanted to see the originating cost centre against each recharge. For any other journal the result is blank. This is a convenience for the analysts, not an input to any calculation.

`DAT02 Actuals Volumes` holds units and revenue by product and region from the hub's volume summary. It is small.

Nothing is typed into a DAT module. A correction to an actual is made in NetSuite and comes through the next load.

## 3.3 Master data and attributes

Attributes of cost centres, accounts, products and regions are held in `SYS02 Cost Centre Attributes`, `SYS03 Account Attributes`, `SYS04 Product Attributes` and `SYS06 Region Attributes`. The first three are loaded from the hub. Region attributes are maintained by Finance Systems, because regions are a planning concept and do not exist in NetSuite.

The account flags `Revenue?`, `Opex?`, `COGS?` and `Sign` are calculated in SYS03 Account Attributes from the loaded account type, although the hub calculates the same flags, because the steering group wanted the spoke to keep working from its own attributes if a hub load failed or the hub was being rebuilt. The same applies to the `Current Period?` flag. The cost is that the flags are defined twice. If the definition of an account type ever changes, it must be changed in both models in the same release.

`SYS03 Account Attributes` has one flag that the hub does not: `Staff?`, which marks the payroll accounts. Staff cost is planned through headcount and not through opex drivers, so the opex logic needs to leave those accounts alone.

`SYS02 Cost Centre Attributes` holds the department, region, legal entity and currency of each cost centre, an active flag and the owner. `Sales CC?` marks the cost centres of the sales department and is used on the revenue pages. The text line item that joins the cost centre code and region code exists for one export to the property team and has no other use.

`SYS07 Launch Flags` works out, by product and month, whether a product has launched and how many months ago. It is in its own module because it is by Products and Time only, and both the volume and revenue logic need it.

## 4.1 Volumes

Planners enter units, price, discount and returns by product and region in `INP01 Volumes`. `CAL01 Volumes` turns the input into sellable units.

For actual months, units come from `DAT02 Actuals Volumes`. For forecast months, units come from the planner's input, unless the planner has ticked `Use Override?`, in which case the override is used. The override exists because the sales directors wanted to be able to replace a statistical baseline with their own number without losing the baseline. The statistical baseline itself was never built and the `Units` input is typed, so the override is rarely used. It is cleared at each roll forward by the action Clear Forecast Overrides.

Returns are a percentage of units, entered by product and region. Net units are units less returns.

A product sells nothing before its launch date. CAL01 Volumes.Launched? is held by Products and Time only, as a subsidiary view inside a Products by Regions module, because the launch date does not vary by region and the builder judged a subsidiary view cheaper than repeating the flag across every region. The implementation partner's usual practice is to avoid subsidiary views in calculation modules. This one was allowed because the flag is read by one line item, `Sellable Units`, in the same module.

Prior year units and volume growth are calculated in `CAL01 Volumes` for the sales pages. They are not used by any downstream calculation.

Volumes are planned in units only. Weight and pallet volumes for the warehouse were discussed and left for a later phase, since the warehouse capacity plan is run in the warehouse management system.

## 4.2 Revenue

`CAL02 Revenue` calculates revenue by product and region from sellable units and price.

Gross revenue is sellable units multiplied by price. Discounts are a percentage of gross revenue. Net revenue is gross revenue less discounts. Rebates paid after the year end are not modelled; Commercial Finance accrues them in the ledger and they arrive in actuals.

Revenue is planned in the currency of the region and converted to sterling using the rate for the region's currency. The conversion is described in section 4.5. `Revenue GBP` is the figure every downstream module reads.

For actual months the model calculates revenue from actual units and the planned price, and does not load actual revenue into this module. The reason is that price is the planner's assumption and the sales directors wanted to see price variance. Actual revenue from the ledger reaches the P&L through `DAT01 Actuals GL` in the usual way, and actual revenue by product from the order system is held in `DAT02 Actuals Volumes` for comparison.

`CAL02 Revenue.VAT` is an indicative figure used in the working capital discussion and is calculated at the UK standard rate of 20 per cent, written into the formula. It is not a tax computation. `SYS00 Model Settings.Default VAT Rate` holds the same rate for display on the assumptions page, and repointing the formula to it is listed in section 7.1.

Two text line items sit in this module. `Actual or Forecast` labels each month for the revenue export. `Revenue Label` joins the product and region names for the same export, because the receiving spreadsheet wanted one key column. Both are held on every month and version, which is wasteful for a label, and both should move to a module without Time and Versions when the export is next changed.

Prior year revenue and revenue growth are calculated here for the sales pages.

## 4.3 Opex forecast logic

Operating expenses are held by cost centre and account in `CAL03 Opex`. Actual months read the ledger for accounts flagged as opex. Forecast months read the drivers that cost centre owners enter in `INP02 Opex Drivers`. `CAL03 Opex.Opex` switches between the two on the actuals flag, and `Opex GBP` converts at the rate for the cost centre's currency.

The drivers are entered by cost centre. The forecast is needed by cost centre and account. Something has to say which driver belongs to which account, and where that mapping lives was the most debated decision in the opex workshops.

Two options were put to Finance Systems. The first was a mapping module by account, holding the driver for each account, which the forecast would read with a lookup. The second was to write the mapping into the forecast formula as a chain of IF branches, one per driver account.

The second option was chosen. The account-to-driver mapping is written into the IF chain of CAL03 Opex.Forecast Opex because Finance Systems did not want planners, or anyone outside Finance Systems, to be able to edit a mapping table, and a change to the mapping is therefore a model change that goes through Finance Systems. In the first year of the spreadsheet process a cost had been moved between accounts in a planning workbook without the ledger following, and the Head of Finance Systems wanted that to be impossible in the new model. A mapping module could have been locked with access rights, but Finance Systems judged that a setting which can be unlocked by a workspace administrator is weaker than a formula, which shows in the model history when it changes.

The cost of this decision is understood. The formula grows by a branch each time Finance adds a driver account, it is harder to read than a lookup, and adding an account needs a model builder. At v1.2 the chain has twelve branches. The implementation partner recommended that the decision be revisited if the chain passes fifteen branches, and that a mapping module with write access limited to Finance Systems would then be the better design.

In the original 2019 build each driver account had its own forecast line item, each with its own IF, and a line that added them up. In v1.2 these are replaced by the single `Forecast Opex` line item in the new module `CAL03 Opex`, because the separate lines were each as large as the whole forecast and the sum had fallen out of step with the drivers. The previous module is renamed `CAL05 Opex OLD` and is kept for the parallel run. Its removal is listed in section 7.1.

Accounts with no branch forecast zero. That is intended: an account that Finance has not given a driver is not planned, and its actuals still appear.

## 4.4 Opex drivers input

`INP02 Opex Drivers` is where cost centre owners enter their forecast. It is by cost centre and month, with one line item per driver: rent, business rates, utilities, travel and so on.

INP02 Opex Drivers holds one line item per driver, instead of a Drivers list, so that each driver can carry its own guidance note and so that the budget spreadsheet template loads into the module column for column. The cost centre owners had used the same template for several years, and the action Import Budget from Excel was built to take it unchanged. A Drivers list would have been the more conventional design and would have removed the long total formulas. It was rejected in 2019 for the reasons above and because, with the mapping held in a formula, a list would have given no advantage in the forecast logic.

The result is a wide module. It has grown as Finance has asked for more detail, and not every driver has an account branch in the forecast yet. A driver without a branch is collected for information and reported through the subtotals only.

The module holds a small amount of arithmetic, against the rule in section 2.1, because the owners wanted to see totals as they type. `Total Drivers` adds every driver and must be extended whenever a driver is added. The four subtotals (property, people, marketing and IT costs) are for the input page. `Check` compares the total with the subtotals and was meant as a control that a new driver had been added to the total. `Has Drivers?` and `Driver Count` let FP&A count how many cost centres have submitted.

`CAL12 Driver Phasing` holds a phased copy of the main drivers for the management pack, showing the forecast months only. Each phased line is zero in actual months and the driver in forecast months.

Drivers are entered in the cost centre's own currency. They are not entered by account, and cost centre owners do not see the chart of accounts anywhere in their pages.

## 4.5 FX

Caldergate plans in four currencies: sterling, euro, US dollar and Polish zloty. Each region and each cost centre has a currency attribute.

Rates are held in `SYS05 FX Rates` by currency, month and version, as `Rate to GBP`. Revenue is converted at the rate for the region's currency and opex at the rate for the cost centre's currency. Conversion is at the average rate for the month. There is no closing rate, because the model has no balance sheet to translate.

Rates are held by version so that the Budget version keeps the rates the budget was set at. `Rate Locked?` is ticked by Finance Systems when a month's rate is final. `Rate to GBP Prior` and `Rate Movement` are shown on the assumptions page so that a mistyped rate is obvious.

The rates come from Group Treasury, who prepare a file of month-average rates on the first working day of each month. The file is loaded by Finance Systems using the action Import FX from Treasury file. This is the one import in the model that does not come through the data hub. Treasury's rates are a planning assumption, not source system data, and the hub's owners did not want assumptions in the hub.

Import FX from Treasury file is run by hand and sits outside every process because the Treasury file is sometimes late and the monthly actuals load must not wait for it. If the file has not arrived, the previous month's rate stays in place until it does, and Finance Systems tells FP&A that the rates are provisional.

The risk in this arrangement was recorded at the time: it depends on one person in Treasury sending a file and one person in Finance Systems loading it. An automated rate feed was priced and declined in 2019 on cost. If the Treasury file ever stops, the rates in `SYS05 FX Rates` will go stale without any error, and the first sign will be a translation difference against the consolidation.

No rate is to be written into a formula. Any line item that needs a rate reads `SYS05 FX Rates`.

## 4.6 Margin

`CAL04 Margn` calculates cost of goods and gross margin by product and region.

Cost of goods is sellable units multiplied by landed cost. Landed cost is entered by product in `INP06 Unit Costs` as a unit cost plus freight per unit. It is by product and month and does not vary by region. Procurement confirmed that inbound freight is negotiated per product line, not per destination, and that outbound freight is an operating expense of the warehouse cost centres.

Margin is net revenue less cost of goods. Margin % is margin divided by net revenue. Margin is converted to sterling at the region's rate in the same way as revenue.

Standard costing was discussed. Caldergate revalues stock at standard cost twice a year, and the purchase price variance is posted to a ledger account. The model does not attempt to reproduce the variance. Planned cost of goods is at the planner's unit cost, and the difference from the ledger appears as a margin variance for FP&A to explain. This was accepted by Commercial Finance on the grounds that explaining the variance is their job and the model should not hide it.

Stock is not modelled. Unit costs apply to units sold in the month, with no opening or closing stock and no cost flow assumption.

The margin by product is the most commercially sensitive data in the model. Access to the margin pages is restricted by role, as described in section 6.1.

## 4.7 Headcount cost

Headcount is planned by cost centre and role in `INP03 Headcount`. Planners enter FTE, annual salary per FTE and a bonus percentage. The module calculates monthly salary, employer National Insurance, bonus and pension, and a total cost.

This module is an input module that also calculates, which is against the naming rule. The cost centre owners asked to see the cost of a hire on the same grid as the hire, and the calculation is short, so the exception was agreed.

Employer National Insurance is calculated on the monthly salary above the monthly threshold. The annual threshold and the rate are held once, in `SYS00 Model Settings`, and Finance Systems updates them each April.

Employer pension is calculated at a flat 5 per cent of monthly salary in INP03 Headcount.Pension because the group scheme has a single employer contribution rate, and in 2019 Finance Systems chose to write it into the formula instead of adding a setting for one number. The implementation partner advised against this and it is listed in section 7.1.

Salary is an average for the role in the cost centre. The model holds no individual salaries, by decision of the HR Director, and the selective access described in section 6.1 means a cost centre owner sees only their own cost centres.

Starters and leavers within a month are not pro-rated. A change in FTE takes effect for the whole month. Pay awards are entered as a new salary from the month they apply.

The total cost by cost centre feeds staff cost in the P&L. It does not pass through the opex logic, and the payroll accounts are excluded from the opex forecast by the `Staff?` flag.

When the workforce model is live, FTE, salary and bonus percentage will be imported into this module in place of the planners' input. The partner building that model will document the feed and any change it makes to this module.

## 4.8 P&L by cost centre and department summary

`CAL07 P&L by Cost Centre` brings the pieces together by cost centre and month.

Revenue and cost of goods are planned by product and region, not by cost centre. Each product has a revenue cost centre attribute, and the P&L sums revenue and cost of goods to that cost centre. The alternative, summing by region to a sales cost centre, was rejected because several regions share one sales team.

Opex comes from `CAL03 Opex`, summed across accounts by the module's dimensions. Staff cost comes from `INP03 Headcount`, summed across roles. EBITDA is gross margin less opex less staff cost. Depreciation comes from `CAL10 Depreciation`, and EBIT is EBITDA less depreciation.

The P&L stops at EBIT. Interest and tax are group items that are not planned by cost centre. A tax estimate is made in the cash flow.

`Opex Budget` selects the Budget version of opex so that the variance to budget can be shown beside the forecast on the cost centre owner's page. This is one of the permitted uses of a version named in a formula.

`CAL06 Department Summary` sums the P&L by department, using the department attribute of the cost centre, and adds FTE and cost per FTE. It exists because department is an attribute and not a level of the hierarchy, so the summary has to be calculated. The same approach is used for legal entity in the cash flow.

`CAL11 Reporting Prep` restates the P&L lines that the packs use and adds total cost. Section 5.1 explains why the packs read this module and not the P&L directly.

Allocations of central costs to trading cost centres are out of scope. Central cost centres show their own costs and a negative EBITDA.

## 4.9 Depreciation

Depreciation was added in v1.1 when the Financial Controller asked for EBIT by cost centre.

Capital expenditure is entered by cost centre and month in `INP04 Capex`, with the asset class, the useful life in years and an optional project. A cost centre plans one asset class. The few cost centres that buy more than one class were split in NetSuite at the same time, at the Financial Controller's request.

The charge is straight line, starting in the month of spend, with no residual value. `CAL10 Depreciation` holds two line items: `Charge` and `NBV`.

CAL10 Depreciation.Charge is long because it has one branch per asset class, each with its own useful life, and it is written that way so that the charge reconciles to the fixed asset register class by class. The classes and lives are those in the group accounting policy:

| Asset class | Life | Branch |
|---|---|---|
| IT equipment | 3 years | Spend over the last 36 months, divided by 36 |
| Vehicles | 5 years | Spend over the last 60 months, divided by 60 |
| Warehouse racking and fixtures | 7 years | Spend over the last 84 months, divided by 84 |
| Plant and handling equipment | 10 years | Spend over the last 120 months, divided by 120 |
| Leasehold improvements | More than 10 years, treated as 20 | Spend over the last 240 months, divided by 240 |
| Low-value and other | Under 3 years | Spend divided by 12 |

A cost centre with no asset class has no charge.

A shorter formula was tried first: one moving sum whose window was the useful life in months. It did not survive testing, because the window of a moving sum cannot be taken from a line item that varies by cost centre without a much more expensive construction, and the first attempt did not agree with the register for vehicles. The branch per class was the form that agreed. The lead model builder tested it against the fixed asset register for every class for the twelve months to March 2020, and it agreed to the pound.

The formula should not be shortened for tidiness. Any rewrite has to be run beside the present formula and checked against the asset schedule for every class before it replaces it. If the accounting policy adds a class or changes a life, a branch is added or changed, and the check is repeated.

Spend before the start of the model calendar is outside the moving sum. Opening assets are therefore loaded as spend in the first model month for the remaining life, which the Financial Controller's team prepares once a year at the roll.

## 4.10 Cash flow

`CAL08 Cash Flow` is an indirect cash flow by legal entity and month. It was asked for by the Group Treasurer as a planning view, and it is not a substitute for the thirteen-week cash forecast that Treasury runs from bank data.

EBITDA and revenue are summed from the P&L by the legal entity of each cost centre. Debtors are revenue multiplied by debtor days over thirty, with debtor days entered by legal entity in `INP05 Balance Sheet Drivers`. The working capital movement is the change in debtors from the previous month. Creditor days and stock days are collected in the input module for a later phase and are not yet used.

Tax is an estimate: positive EBITDA multiplied by the main rate of corporation tax, which is written into the formula. Capital expenditure is summed from `INP04 Capex`. Net cash flow is EBITDA less tax, less capex, less the working capital movement.

Opening cash for each month is the closing cash of the month before, and closing cash is opening cash plus net cash flow. CAL08 Cash Flow.Opening Cash reads the previous month's Closing Cash, and takes the entered opening balance in the first month of the model, because that is the standard way to carry a balance forward in Anaplan and it is not a circular reference. A model checker may report the pair as a cycle. It is not one, since each month reads only the month before.

`Cash Negative?` flags any month in which a legal entity's closing cash is below zero, for a conditional format on the Treasurer's page.

The cash flow ignores intercompany funding, dividends and loan movements. Treasury add those outside the model.

## 5.1 Reporting packs

Two output modules feed the packs: `OUT01 Management Pack` and `OUT02 Board Pack`. Both are by cost centre and month.

The management pack lines read `CAL11 Reporting Prep`, plus headcount, capex, depreciation and the phased drivers. The board pack lines read the management pack. OUT02 Board Pack reads OUT01 Management Pack, and not the calculation modules, so that the board pack and the management pack can never show different numbers for the same line. In the spreadsheet process the two packs were built separately and had disagreed more than once. The chain from the P&L through reporting prep to the two packs is longer than a model builder would normally choose, and it was chosen for that assurance. It also means the P&L can be restructured without touching a pack, since only `CAL11 Reporting Prep` needs to follow.

Line items in OUT01 Management Pack and OUT02 Board Pack keep Versions, even where a line's formula does not need them, because the board compares Actual, Forecast and Budget side by side on the pack views. The extra cells are the price of that comparison and are not to be treated as waste when the model is sized. The same is not true of calculation and input modules, where a dimension a formula does not need should be removed.

The board pack has budget and variance lines that select the Budget version by name. This is the other permitted use of a named version.

Summaries are left on in the output modules. The packs show quarter, year and group totals, and the pages were built before the final list of lines was settled. A later tidy-up should switch off summaries on lines that no page shows in total.

The packs are produced by the action Export Board Pack inside the process Publish Board Pack, which FP&A run after the forecast is rolled. The board papers themselves are assembled outside Anaplan.

## 6.1 Security and roles

Four roles were created.

| Role | Who | Access |
|---|---|---|
| Finance Systems Admin | Finance Systems | Workspace administrator. Full access. Runs all processes. |
| FP&A Analyst | FP&A team | Read all modules. Write to input modules for all cost centres. Run the roll forward and publish processes. |
| Planner | Cost centre owners and delegates | Write to the input modules for their own cost centres. Read the P&L for their own cost centres. |
| Executive | Directors | Read the output modules and pages. No write access. |

Selective access is switched on for Cost Centres. A planner is given write access to their own cost centres and no access to the rest. The department heads have read access to every cost centre in their department. Selective access is maintained by Finance Systems from the cost centre owner held in NetSuite, and reviewed twice a year with Internal Audit.

Products and Regions do not have selective access. The margin pages are restricted by role instead: only FP&A Analyst and Executive can open them.

Actual months are locked for planners by a write access driver built on the actuals flag. `SYS00 Model Settings.Lock Actuals?` lets Finance Systems switch the lock off for a correction, and it is expected to be on at all times outside the roll forward.

Single sign-on is used for all users. There are no shared accounts. The integration user that runs the scheduled imports is a named service account owned by Finance Systems.

Model changes are made by Finance Systems only. At go-live the model was not under application lifecycle management, and changes were made in production in a maintenance window. Moving to a development and production pair was recommended and is listed in section 7.1.

## 6.2 Processes and actions

The model has five processes.

| Process | Run by | When | What it does |
|---|---|---|---|
| Monthly Actuals Load | Scheduled | Working day 3 | Imports GL actuals and volumes from the hub |
| Master Data Refresh | Scheduled | 1st of the month | Imports cost centres, products and accounts from the hub |
| Roll Forecast | Finance Systems | After the actuals load | Clears forecast overrides and copies actuals into the forecast inputs for the closed month |
| Headcount Refresh | Finance Systems | Working day 5 | Refreshes headcount inputs |
| Publish Board Pack | FP&A | After the roll | Exports the board pack and the P&L |

The order matters. The master data refresh runs before the actuals load, so that a new cost centre or account exists before data arrives for it. The roll forward runs after the actuals load and before the packs are published.

Every import that is part of the monthly cycle belongs to a process. An import that is run by hand, outside a process, is an exception and its reason is recorded in the section that covers it. At v1.2 the exchange rate import is the only such exception by design.

Imports from spreadsheets are limited to the budget template described in section 4.4. Planners cannot run imports.

When an import is replaced, the old action is deleted once the new one has run successfully for one close. Old actions left in the list are a risk, since a user with the right role can run them.

Exports to spreadsheets are provided for the board pack, the P&L and the opex drivers. Exports that nobody has scheduled should be reviewed once a year and removed if no one claims them.

## 6.3 Testing

Testing was in three stages.

Unit testing was done by the build team as each module was completed. Each calculation module was checked against a hand calculation for three cost centres or three products chosen by FP&A, including one with unusual data.

Reconciliation testing was done by FP&A and Group Reporting. The tests and their tolerances were:

| Test | Compared with | Tolerance |
|---|---|---|
| Actual opex by cost centre and account | NetSuite trial balance | Nil |
| Actual units and revenue by product | Sales order report from the hub | Nil on units, 0.1 per cent on revenue |
| Forecast opex by cost centre | The final spreadsheet forecast for the same period | Explained differences only |
| Headcount cost by cost centre | Payroll summary | 1 per cent |
| Depreciation by asset class | Fixed asset register | Nil |
| Board pack lines | Management pack lines | Nil |

User acceptance testing was run over two weeks with twelve cost centre owners, two from each of the larger departments. They entered a forecast in the model and in the old workbook, and the two were compared. The main findings were about page layout and the order of the drivers, not the calculations.

A parallel run was held for the first quarter after go-live. A second parallel run is being held for the revised opex logic in v1.2: the old and new opex modules run side by side, and FP&A compare them at each close until Finance Systems sign off the new one.

Test evidence is kept by Finance Systems for Internal Audit. After any change to a formula in a calculation module, the reconciliation test for that module is repeated before the change is released.

## 6.4 Performance and sizing

The model's size is dominated by two shapes. The first is Cost Centres by Accounts by month by version, used by the actuals and the opex logic. Each line item of that shape has about five million cells. The second is Products by Regions by month by version, used by volumes, revenue and margin, which is much smaller.

The guidance agreed with Finance Systems is as follows.

- A new line item by cost centre and account needs a reason. Each one costs about as much as the whole of the revenue logic.
- Text line items are avoided at the large shapes. The exception is the journal reference described in section 3.2.
- Functions that work on text or on item names, such as joining names or finding an item from text, are kept out of the large shapes for the same reason.
- Summaries are switched off on line items that no page shows in total, flags and rates in particular.
- A setting that is one number is held once, in `SYS00 Model Settings`, and not repeated across a planning module.

At go-live the model opened in under a minute and the monthly actuals load completed in about a minute. A full recalculation, as triggered by changing the forecast start month, took a few seconds. These figures should be re-measured each year after the roll.

Cost centre by account sparsity is high: most cost centres use fewer than forty accounts. A sparse design using a combined list was considered and rejected in 2019 on the grounds of complexity for the cost centre owners' pages. It should be reconsidered if the number of cost centres or accounts grows materially.

The model is expected to hold three versions. A fourth version would add about a third to the cells in every versioned module.

## 7.1 Open items

The following were open when v1.2 was issued. Each has an owner in Finance Systems unless stated.

1. **Scenario planning.** CAL09 Scenario Planning was created as an empty placeholder because scenario planning was taken out of phase 1 scope in February 2019 and the steering group wanted the module number and the Scenarios list reserved for a later phase. No design exists. When it is designed it should flex the existing volume, revenue and opex modules and should not copy them.
2. **Removal of the old opex module.** `CAL05 Opex OLD` is to be removed when the parallel run described in section 6.3 is signed off. It is as large as the module that replaced it and nothing should be built on it.
3. **Opex mapping.** The decision in section 4.3 should be revisited if the chain passes fifteen branches.
4. **Rates and percentages written into formulas.** The VAT rate in `CAL02 Revenue`, the tax rate in `CAL08 Cash Flow` and the pension rate in `INP03 Headcount` should each read a setting in `SYS00 Model Settings`. None is urgent while the rates are stable.
5. **Exchange rate feed.** The manual Treasury file in section 4.5 remains a dependency on two people. An automated feed should be priced again.
6. **Label line items.** The two text line items in `CAL02 Revenue` should move to a module without Time and Versions.
7. **Old hub imports.** Each import from Caldergate Hub v1 is to be deleted after its replacement has run for one close. The cost centre import is the last.
8. **Notes.** Most modules and many line items have no note. A pass to add them was planned for the end of the build and was not done.
9. **Development and production.** The model should be moved to a development and production pair before the next significant change.
10. **Creditor and stock days.** Collected in `INP05 Balance Sheet Drivers` and not yet used in the cash flow.
11. **Working days.** Calculated in `SYS01 Time Settings` and little used. Either phase costs on them or remove them.
12. **Unused driver detail.** Drivers in `INP02 Opex Drivers` without an account branch should either be given one or be removed from the input page.

Open items are reviewed at the monthly steering meeting. An item is closed by a change to the model and a reissue of this record.
