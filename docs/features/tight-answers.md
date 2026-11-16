# Tight answers and "beyond the exports"

## What it does

An answer is short on purpose. It has a lead of at most three sentences, then the graphic for its kind of question,
then the evidence. The words do not repeat what the graphic shows.

Two things make that so:

1. **The shape is asked for.** The instructions set it: a lead of at most three sentences, at most three short
   sections of bullets, at most two quoted passages, about 250 words outside the quotes.
2. **The draft is edited.** When a Full answer comes back long, one short extra model call cuts it. Then the
   validator checks the edited text, exactly as it would have checked the draft.

Under the lead, one line says what the answer read besides the exports:

> BEYOND THE EXPORTS  Read 2 of 6 documents and 6 owner notes:  [design decision record]  [steering notes]  [note]

Each name opens its source. The notes the answer cites are shown; the ones it was handed and did not cite are behind
"+4 not cited". When nothing but the exports was read, the line says so.

## The editor may only cut

That is not left to the model's word. Code compares the edit with the draft and throws the edit away, keeping the
draft, when the edit:

- holds a name or a citation id the draft did not;
- holds a figure the draft did not;
- changed a single character inside a quoted passage;
- dropped a citation the lead rests on, the Brief itself, or the words *Not recorded*;
- is not shorter.

What the code cannot see is a new claim in plain words with no name, figure or quote in it. The editor is told not to
add one, and it is given only the question and the draft, so it has nothing to add from.

## How to use it

Nothing to do: it is on. It runs for Full answers of 170 words or more; Concise answers are already short.

- **See it**: the run timeline under an answer has an `edit` step before the validator, with the words before and
  after (`794 → 239 words`), or `draft kept:` and the reason.
- **Turn it off for yourself**: Settings, *Editing pass*, Off.
- **Turn it off for the instance**: `ARCHITECT_EDIT_PASS=0`.

It is a model call like any other: on your spend, stopped at your cap (the draft then stands).

## Ask next

An answer is short, so the depth is in the second and third question. Under every answer are two or three questions
to ask next. One click asks it in the same chat, so the architect already has the earlier answer in mind.

Each leads from the feature the answer showed into another one:

| After | It offers |
|---|---|
| Why | how it is calculated, a plan to change it, what a change would reach |
| How it is calculated | why it was built this way, what a change would reach, what the documents say |
| A build plan | what the change reaches, the Planual flags explained, what to check once built |
| An overview | what to fix first, what a new builder reads first |
| The review | a plan for the first fix, the reach and the reason of the object it leads with |
| The reach of a change | what to test first, what the documents say, why it was built this way |
| What the documents say | why it was built this way, what a change would reach |
| Not recorded | what the documents say about it, what a change would reach |

They are made by code, not by the model. Each kind of answer has its next questions, filled in with the object the
answer was about: the line item the formula was drawn for, the selection the reach was read from, the object the
documents were followed from. So they cost nothing, and they can never name something your model does not have. A
question about a formula is not offered for a module, and one that needs an object is left out when the answer had
none.

## What "read" means in the line

- **Documents**: a document counts when the answer read one of its sections in full or cites one. A document that only
  came up in a search does not count.
- **Owner notes**: the notes the store handed the model for this question. Those the answer cites are named first.
- The line is computed by the server from what happened in the turn, never taken from the answer's own words.

## How it is built

- `src/anaplan_architect/edit.py`: the editor's instructions, `refused()` (the guard), `prose_words()` (words outside
  quoted passages, fenced blocks and ids), `beyond_line()`.
- `Session._edit`, `Session._edits` and `Session._beyond` in `src/anaplan_architect/chat.py`; the shape is the
  "Shape every answer" paragraph of `CHAT_SYSTEM`.
- The line is the `beyond` block of a turn, drawn by `Beyond` in `web/src/views/Answer.tsx`.
- Ask next: `src/anaplan_architect/followups.py` (`suggest`, `subject_of`), the `followups` block of a turn, drawn at
  the foot of `TurnView` in `web/src/views/Answer.tsx`. Tests: `tests/test_followups.py`.
- Tests: `tests/test_tight.py`.
