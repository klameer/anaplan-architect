# Workforce Planning: partner handover note

From: the implementation partner for Workforce Planning (the second partner engaged by Caldergate Distribution Group).
To: HR Analytics (model owner) and Finance Systems (owner of Caldergate FP&A and Caldergate Data Hub).
Date: 24 September 2021. Our engagement ends on 30 September 2021.

This note hands the Workforce Planning model over to HR Analytics. It covers what the model does, how it is named, what has to be done by hand each month and each year, how it feeds Caldergate FP&A, and the things we left unfinished or would do differently.

## 1. What the model does

Workforce Planning holds cost at employee level. `Data - Employees` is loaded from Workday. `Calcs - Cost` works out each employee's monthly salary, applies the pay award from the month it takes effect, and adds employer National Insurance, pension and bonus. `Calcs - Headcount by CC` sums FTE and cost to cost centre and role. `Reports - Headcount` sums to department for HR's own reporting. `Calcs - Attrition` counts leavers by role.

The model replaces the cost centre and role input that planners used to type into Caldergate FP&A. FP&A now receives headcount from this model once a month.

## 2. Naming

Workforce Planning uses our own naming (Data -, Inputs -, Calcs -, Reports -) and not the SYS, INP, DAT, CAL and OUT prefixes of Caldergate FP&A, because HR Analytics own the model, are not Anaplan builders, and asked for module names in plain words. We raised the difference with Finance Systems at the design review and it was accepted for a model they do not own.

The rough equivalents are: Data is DAT, Inputs is SYS and INP together, Calcs is CAL and Reports is OUT. There are no module numbers. Modules are ordered in the model by the order of calculation.

Please do not rename the modules to match FP&A without checking the saved views and the export definitions first. Both are tied to the present names in the documentation HR Analytics hold.

## 3. Manual steps

Each month, in this order:

1. HR Analytics set `Inputs - Settings.Current Period` and `Forecast Start`.
2. HR Analytics run the process Monthly Refresh. It imports employees from Workday and the cost centre map from the Data Hub.
3. HR Analytics check the leavers and the headcount total against the Workday headcount report.
4. HR Analytics run the process Push to FP&A, which exports headcount cost.
5. Finance Systems run Headcount Refresh in Caldergate FP&A, which imports the file. See section 5.

Step 5 is in a different model with a different owner. Nothing in Anaplan makes step 5 wait for step 4. If FP&A is refreshed first, it loads last month's headcount without any error. Agree the day with Finance Systems; we have used working day 4 for this model and working day 5 for FP&A.

Each year:

- In April, after Finance Systems update the National Insurance threshold and rate in FP&A, run Import from Caldergate FP&A - Assumptions by hand to bring them into `Inputs - Settings`. The import is deliberately in no process, because it must only run after FP&A has been updated. The pension rate, the pay award and the month it applies from are typed.
- Key weekend days and bank holidays in `Inputs - Calendar` for the new year.

## 4. Workday is loaded directly

Workforce Planning loads employees straight from Workday and does not take them from the Data Hub, because the hub's employee master holds no salaries and the HR Director would not allow salary data in a model owned by Finance. The hub also loads employees from Workday, for cost centre and role only. The two loads run on different days and from different Workday reports, so the two employee lists can differ for a few days around a starter or leaver. Nothing reconciles them.

Data - Employees.Employee Name is a text line item held on every month because HR Analytics asked to see names, not employee numbers, on the monthly leavers view, and the module was built with Time before we separated the monthly flags from the static attributes. The static attributes (name, cost centre, role, salary, dates) should be in a module without Time. We ran out of days to move them.

## 5. The feed into FP&A

Export Headcount Cost to FP&A exports `Calcs - Headcount by CC`. In Caldergate FP&A, the import Import from Workforce Planning - Headcount Cost loads it into `INP03 Headcount`: FTE to `FTE`, average salary to `Salary`, and bonus percentage to `Bonus %`. FP&A then calculates the cost itself from those three inputs. We did not load our total cost, because Finance Systems wanted `INP03 Headcount` to keep calculating in the way their design record describes, so that the P&L did not change shape.

Two consequences follow.

First, the cost in FP&A is calculated on the average salary of a role in a cost centre, and ours is calculated per employee. National Insurance has a threshold, so the two do not agree exactly. The difference at go-live was under 0.5 per cent of total cost, and Finance Systems accepted it.

Second, some logic now exists twice. `Employer NI` and `Working Days` are written in both models, to the same formula, by two different partners. If the National Insurance rules change shape, and not just rate, both must be changed.

Calcs - Headcount by CC.Bonus % is a fixed 0.1 on every cost centre, role and month because it exists only to give the export file a bonus column in the layout that INP03 Headcount expects. `Calcs - Cost.Bonus` uses the same 0.1. HR confirmed a flat 10 per cent bonus accrual for all roles for 2021 and we wrote it into both formulas. It should be a setting in `Inputs - Settings`.

## 6. Changes we made in FP&A

With Finance Systems' agreement we made one change inside Caldergate FP&A.

We added INP03 Headcount.NI Threshold and INP03 Headcount.NI Rate to INP03 Headcount, next to the salaries, because we wanted the threshold and the rate visible on the same grid as the salaries they are applied to when the imported figures are checked each month. Both read `SYS00 Model Settings`, so the values are still entered once. The cost is that two single numbers are repeated on every cost centre, role, month and version. With hindsight they belong in `SYS00 Model Settings` only, with the `Employer NI` formula reading them there, and Finance Systems can move them safely if the formula is repointed in the same change.

We did not touch the pension line in `INP03 Headcount`, which has its rate written into the formula. That predates us.

## 7. The old hub import in FP&A

While testing the feed we found the action Import from Caldergate Hub v1 - Cost Centres still in the FP&A action list. It loads `SYS02 Cost Centre Attributes`, the same module as the Data Hub import that replaced it.

Import from Caldergate Hub v1 - Cost Centres was left behind because the old hub was switched off in March 2021 before the first partner had deleted the action, the first partner's support ended soon after, and we were asked not to delete anything in FP&A that we had not built. It last ran on 19 March 2021 and is in no process. Its source model no longer exists, so it cannot run successfully. It is safe for Finance Systems to delete.

## 8. Other things to know

- Calcs - Attrition.Leavers is held by employee inside a module by role, as a subsidiary view, because the leavers dashboard was built on Calcs - Attrition in the last week and we put the employee-level flag where the dashboard could reach it. It should be in `Data - Employees`.
- zz Archive - 2021 Cost is a copy of headcount and cost by role that we kept to compare the model with the 2021 payroll summary at go-live, and it can be deleted once HR Analytics have filed that comparison. It still calculates.
- `Calcs - Attrition.Attrition %` divides without protection against zero headcount. A role with no headcount shows zero, which is what HR wanted.
- The export Export Leavers Report is not scheduled. HR Analytics run it on request.
- There is no development model. Changes are made in production. For a model of this size that has been manageable, but any change to the export to FP&A should be tested in a copy of both models first, and agreed with Finance Systems as the owner of the receiving model.

## 9. Contacts

After 30 September questions go to the HR Analytics Lead for this model and to the Head of Finance Systems for anything in Caldergate FP&A or the Data Hub. We hold no copy of Caldergate data after the engagement ends.
