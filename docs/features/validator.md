# The validator

## What it does

Every answer is checked by code before you see it. What cannot be supported is flagged on the answer, not smoothed
over. The foot of each answer carries the verdict: **VERIFIED**, or what was found.

## What is checked

| Check | What it means |
|---|---|
| **Names** | Every model, module, line item and action the answer names is looked up in the estate. A name the estate does not have is listed as *not found*. |
| **Looked up or not** | A real object the answer named without having looked it up this conversation is listed as *unchecked*, with a click to look it up. |
| **Citations** | Every citation id in the answer must be one the tools handed out. An id that was never handed is a *phantom*. |
| **Figures** | Every number in the answer must appear in what the tools returned this turn, or follow from those by simple arithmetic. One that does not is *untraced*. |
| **Quotes** | Every quoted passage beside a section id must be in that section, word for word. One that is not is flagged and marked on its source card. |
| **Why** | A why-answer must rest on a passage or an owner note. With neither, it must say *Not recorded*; if it gives a reason anyway, the page heads the answer "Not recorded" itself. |
| **Build plans** | A plan is parsed, resolved and ordered by code before it is shown at all: [Build plans](build-plans.md). |

Click any name in an answer to open the evidence: its formula, its dimensions, what it reads, what reads it, and the
row of the export it came from.

## What it does not do

It checks that what an answer says is in the estate and the documents. It does not judge whether the reasoning is
good, and it does not detect an answer steered by a hostile document: see [Security](../SECURITY.md).

## How it is built

- `assess_answer`, `figures` and `verification_of` in `src/anaplan_architect/chat.py`; quotes in `check_quotes` in
  `src/anaplan_architect/orac/documents.py`.
- Citations are minted by the tools as they hand objects to the model (`orac/evidence.py`) and stored with the
  answer, so an old answer's evidence still opens after a newer upload.
- The parse and the formula graph come from [anaplan-estate](https://github.com/klameer/anaplan-estate) and
  [anaplan-grammar](https://github.com/klameer/anaplan-grammar).
- Tests: `tests/test_answer_contract.py`, `tests/test_stage3.py`, `tests/test_documents.py`.
