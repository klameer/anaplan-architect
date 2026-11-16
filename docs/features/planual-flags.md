# Planual flags

## What it does

It flags the Planual rules it can see in an export: 18 rule numbers across 24 checks. It does not check the Planual.

The flags are advisory. You have the rules in front of you; you do not have to follow them. A flag says *as per*
this rule number or *departs from* it, with one line of why in your model's own terms. A departure never rejects a
plan and never changes a verdict: you may have a reason, and often a document or an owner note already records it.

Only rule numbers and the tool's own wording appear. The Planual's text is never shown.

## On a build plan

Ask for a plan. Each planned line item, and each existing formula the plan changes, carries its flags under the
formula:

> `Departs from Planual 2.02-01, 2.02-02`  13 IF THEN ELSE in one formula
>
> `As per Planual 2.01-09, 2.02-12`  no hard-coded figure: what it uses is read from line items

Departures come first. The **Planual flags** line under the plan counts them and says they are flags only. The
Markdown export of the plan lists them too.

How it is done: the plan's new line items and changed formulas are merged into a copy of the model, and the checks
that can be judged before anything is built are run over the copy. Those are the ones that read a formula, a format
or a summary method. The checks that need cell counts or usage (unused line items, over-dimensioned line items) say
nothing about a line item that does not exist yet, so they are not run.

## On improvements

Each finding card shows the rule numbers its finding rests on, such as `Planual 2.02-01, 2.02-02`, or
`the tool's own test` when no Planual rule is behind it (a percentage summed, a circular reference, a name that
says leftover).

Where the owner has already decided, the card says **kept on purpose** and names what records it, which opens:

- an owner note of type decision or constraint on the object or its module, that says it is kept, deliberate or not
  to be changed;
- a document section that names the object and says it is kept, deferred or agreed;
- the card's own state, *keep current design*.

The architect is told the same through its tool, so the answer does not raise a decided thing as new.

## Limits

- 18 numbers across 24 checks is what an export can show. Naming conventions, model settings, user access,
  dashboards and anything about data are not in an export and are not flagged.
- A flag is a pattern in a formula or a setting, measured by code. It is not a judgement that the rule was broken
  for a bad reason.
- *As per* is said only where a line item exercises a rule (it has an IF, a summary method, a lookup). Silence on a
  rule means the line item gave it nothing to judge, not that it passed.

## How it is built

- `src/anaplan_architect/orac/planual.py`: `flags` and `attach` (the plan), `card_rules` and `kept` (the cards),
  `catalogue` (the count), over the checks in `anaplan_estate.lint`.
- The plan block and its `Flags` in `web/src/views/PlanBlock.tsx`; the cards in `ImproveBlock` and `Kept` in
  `web/src/views/Answer.tsx`.
- Tests: `tests/test_planual.py`.
