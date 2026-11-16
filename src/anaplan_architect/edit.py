"""The editing pass: a drafted answer is cut to what the reader needs, by one short model call, before the validator.

The editor may only cut. That is not left to its word: `refused` compares the edit with the draft and throws the edit
away when it holds a name, a citation id, a figure or a quoted passage the draft did not, when it has lost a citation
the lead rests on, or when it is not shorter. The validator then checks whichever text stands, as it always did.
"""
from __future__ import annotations
import re

EDIT_MIN_WORDS = 170          # a draft shorter than this is left as it is: there is nothing to cut that is worth a model call
TARGET_WORDS = 250            # what an answer aims for outside its quoted passages

# what the page draws for each kind of answer, from the workspace's own data: the editor removes prose that repeats it
DRAWN = {
    "why": "a card for every quoted passage, with its document, section and date",
    "plan": "the build plan as numbered steps, with every module, line item, format, dimension and formula",
    "overview": "a map of the models with the feeds between them and each model's size; a card for every quoted passage",
    "improve": "the ranked finding cards, each with its test, its cells, its share of calculation effort and what was decided",
    "implications": "the reach of the change as rings and steps: how many line items, modules and cells, at what distance, the actions and the other models; a card for every quoted passage",
    "count": "the count, the cells those line items hold, the breakdown by model and module, and the first rows",
    "calculation": "the formula in labelled parts with each reference as a chip, and the upstream trace back to the inputs; a card for every quoted passage",
    "documents": "every section of every document that names the object, grouped by document, with the objects each section names; a card for every quoted passage",
    "general": "a card for every quoted passage, with its document, section and date",
}

SYSTEM = """You are the editor of an answer an Anaplan architect has drafted for a model builder. You cut; you never write.

Return the draft cut down to what the reader needs to decide and act, in the same markdown.

- `## Brief` stays first: at most three sentences that carry the answer and the next step.
- After it, at most three short sections under `##` headings. Turn paragraphs into bullets of one line each. Drop a section that only describes.
- Remove everything that repeats what the page already draws beside the answer (you are told what that is). Remove repetition, hedging, preamble and summary.
- Keep at most two quoted passages, the ones the answer rests on.
- Aim for at most {target} words outside quoted passages.

What you must not do, and it is checked by code, which throws your edit away if you do:
- add anything: no new claim, name, figure, quote or id;
- change a single character inside double quotes: keep a quoted passage exactly as it is with its id straight after it, or remove the quote and its id together;
- change a name in backticks;
- remove a citation the Brief rests on, a question the draft asks the owner, a warning, or a line saying that documents disagree or that something is not recorded.

Reply with the edited answer only: no preamble, no note about what you did."""

_TICK = re.compile(r"`([^`\n]{1,200})`")
_FENCE = re.compile(r"```.*?```", re.S)
_QUOTE = re.compile(r"[\"“]([^\"“”\n]{12,})[\"”]")
_PASSAGE = re.compile(r"[\"“][^\"“”\n]{12,}[\"”]\s*\(?`?[sn]-[0-9a-f]{10}`?\)?")
_ID = re.compile(r"\b(?:[sn]-[0-9a-f]{10}|c[0-9a-f]{10})\b")
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")


def _flat(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("“", '"').replace("”", '"').replace("’", "'")).strip()


def prose_words(text: str) -> int:
    """The words of an answer outside its evidence: fenced blocks, quoted passages with their ids, and bare ids are not counted."""
    t = _FENCE.sub(" ", text or "")
    t = _PASSAGE.sub(" ", t)
    t = re.sub(r"(?m)^\s*>.*$", " ", t)                    # a blockquote is a passage too
    t = re.sub(r"`(?:[sn]-[0-9a-f]{10}|c[0-9a-f]{10})`", " ", t)
    t = re.sub(r"(?m)^\s*\|?[\s:|-]+\|[\s:|-]*$", " ", t)   # a table's rule line
    return len([w for w in re.split(r"\s+", re.sub(r"[#*|>_]", " ", t)) if re.search(r"\w", w)])


def lead_of(text: str) -> str:
    m = re.search(r"(?im)^##\s+Brief\s*$", text or "")
    if not m:
        i = re.search(r"(?m)^##\s+", text or "")
        return (text or "")[: i.start()] if i and i.start() > 0 else (text or "")
    after = text[m.end():]
    j = re.search(r"(?m)^##\s+", after)
    return after[: j.start()] if j else after


def refused(draft: str, edited: str) -> str | None:
    """Why this edit may not replace the draft, or None when it may. An edit may only cut."""
    e = (edited or "").strip()
    if not e:
        return "the editor returned nothing"
    if prose_words(e) >= prose_words(draft):
        return "the edit is not shorter than the draft (no longer worth swapping)"
    if re.search(r"(?im)^##\s+Brief\s*$", draft) and not re.search(r"(?im)^##\s+Brief\s*$", e):
        return "the edit lost the Brief"
    had = {_flat(x) for x in _TICK.findall(draft)}
    new = [x for x in _TICK.findall(e) if _flat(x) not in had]
    if new:
        return "the edit holds a name or id the draft did not: " + ", ".join(new[:3])
    fd = _flat(_FENCE.sub(" ", draft))
    for q in _QUOTE.findall(_FENCE.sub(" ", e)):
        if _flat(q) not in fd:
            return "the edit changed a quote: " + q[:60]
    nums = {n.rstrip(".,") for n in _NUM.findall(_TICK.sub(" ", draft))}
    added = [n for n in _NUM.findall(_TICK.sub(" ", _FENCE.sub(" ", e))) if n.rstrip(".,") not in nums and len(n.strip("%")) > 1]
    if added:
        return "the edit holds a figure the draft did not: " + ", ".join(added[:3])
    lost = set(_ID.findall(lead_of(draft))) - set(_ID.findall(e))
    if lost:
        return "the edit dropped a citation the lead rests on: " + ", ".join(sorted(lost)[:3])
    if re.search(r"not\s+recorded", draft[:600], re.I) and not re.search(r"not\s+recorded", e[:600], re.I):
        return "the edit lost the words Not recorded"
    return None


def request(question: str, kind: str, draft: str) -> str:
    """What the editor is given: the question, what the page draws for this kind of answer, and the draft. Nothing else."""
    return (f"The question: {question.strip()}\n\nThe page already draws, beside this answer: {DRAWN.get(kind, DRAWN['general'])}.\n\n"
            f"The draft follows between the lines.\n\n-----\n{draft.strip()}\n-----")


def beyond_line(documents: int, of_documents: int, notes: int) -> str:
    """One line saying what an answer read besides the exports."""
    n = f"{notes} owner note{'s' if notes != 1 else ''}"
    d = f"{documents} of {of_documents} document{'s' if of_documents != 1 else ''}"
    if documents and notes:
        return f"Read {d} and {n}"
    if documents:
        return f"Read {d}"
    if notes:
        return f"Read {n}" + (f"; none of the {of_documents} document{'s' if of_documents != 1 else ''}" if of_documents else "")
    return "Read nothing beyond the exports" + (f": none of the {of_documents} document{'s' if of_documents != 1 else ''}, no owner note" if of_documents else "")
