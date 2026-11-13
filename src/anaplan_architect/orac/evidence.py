"""Citation ids for what the tools hand the model, and the checks an answer
goes through before it is shown.

Every object a tool returns (model, module, line item, action, pattern, rule)
gets an id bound to the snapshot it was read from. The id is a hash of
(snapshot, kind, model, ref), so it is the same in every conversation over
that snapshot and survives a restart. Owner notes retrieved for a question are
handed the same way (kind "note", provenance from the note's status). An answer
may cite an object only if it was handed this conversation; a real object the
model names without having looked it up is "unchecked", a name the estate does
not contain is "unverified", and an id that looks like a citation but was never
handed is a "phantom": flagged, never rendered as evidence.

Figures go through the same door (a numeral guard, practice 2 in the
plan): every number in an answer must appear in what the model was given this
turn (tool results, the estate material, the question and its notes) or follow
from arithmetic the answer shows over such numbers. What does not is flagged;
nothing is refused, because the reader here is the reviewer and a false refusal
costs more than a marked figure.
"""
from __future__ import annotations
import bisect, hashlib, re
from itertools import combinations
from dataclasses import dataclass, asdict

KINDS = ("model", "module", "line_item", "action", "pattern", "finding", "note", "document")
PROVENANCE = ("observed", "user_confirmed", "inferred", "ai_proposed", "not_established")
CITE_ID = re.compile(r"\bc[0-9a-f]{10}\b")
NOTE_ID = re.compile(r"\bn-[0-9a-f]{10}\b")
SECTION_ID = re.compile(r"\bs-[0-9a-f]{10}\b")      # a section of a project document (orac.documents)


def cite_id(snapshot_id: str, kind: str, model: str, ref: str) -> str:
    h = hashlib.sha1(f"{snapshot_id}\x1f{kind}\x1f{model}\x1f{ref}".encode("utf-8")).hexdigest()
    return "c" + h[:10]


def note_provenance(note: dict) -> str:
    """A note is evidence the owner established, not something the tools observed. A confirmed note is the
    owner's word; one saved from an answer or kept by the chat tool is the AI's proposal until confirmed;
    a working assumption someone typed is not yet established."""
    if note.get("status") == "user_confirmed":
        return "user_confirmed"
    if note.get("origin_kind") in ("answer", "chat_tool"):
        return "ai_proposed"
    return "not_established"


@dataclass
class Citation:
    id: str
    kind: str
    model: str            # the model the object lives in ("" for a rule or a note)
    ref: str              # the object as the estate names it: "Module.Line Item", "Module", action name, pattern id, rule id, note id
    name: str             # how the model sees it in a tool result (a note: its title)
    snapshot_id: str
    provenance: str = "observed"
    tool: str = ""        # the tool that first handed it ("notes" for an owner note)

    def to_dict(self) -> dict:
        return asdict(self)


class Evidence:
    """One per conversation: everything handed to the model, by id and by name."""

    def __init__(self, estate_id: str = "", snapshot_id: str = ""):
        self.estate_id = estate_id
        self.snapshot_id = snapshot_id
        self.handed: dict[str, Citation] = {}
        self.by_name: dict[str, str] = {}

    def mint(self, kind: str, model: str, ref: str, name: str | None = None, tool: str = "", provenance: str = "observed") -> Citation:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if provenance not in PROVENANCE:
            raise ValueError(f"provenance must be one of {PROVENANCE}")
        cid = cite_id(self.snapshot_id, kind, model, ref)
        c = self.handed.get(cid)
        if c is None:
            c = Citation(cid, kind, model, ref, name or ref, self.snapshot_id, provenance, tool)
            self.handed[cid] = c
        for n in self._names(c):
            self.by_name.setdefault(n, cid)
        return c

    @staticmethod
    def _names(c: Citation) -> list[str]:
        out = [c.name.lower(), c.ref.lower()]
        if c.kind in ("module", "line_item") and c.model:
            out.append(f"{c.model} :: {c.ref}".lower())
        if c.kind == "action":
            out.append(f"action:{c.ref}".lower())
        if c.kind == "pattern":
            out.append(f"pattern:{c.ref}".lower())
        if c.kind == "finding":
            out.append(f"finding:{c.ref}".lower())
        if c.kind == "note":
            out.append(f"note:{c.ref}".lower())
        if c.kind == "document":
            out = [c.ref.lower()]                      # a section is cited by its id only: its title is prose, not a name
        return out

    def restore(self, rows: list[dict]) -> None:
        """Rehydrate from citations recorded on earlier turns (a resumed conversation keeps what it was handed)."""
        for r in rows or []:
            try:
                c = Citation(**{k: (r.get(k) or "") for k in ("id", "kind", "model", "ref", "name", "snapshot_id", "provenance", "tool")})
            except TypeError:
                continue
            if c.id and c.id not in self.handed:
                self.handed[c.id] = c
                for n in self._names(c):
                    self.by_name.setdefault(n, c.id)

    def resolve(self, cid: str) -> Citation | None:
        return self.handed.get(cid)

    def lookup(self, name: str) -> Citation | None:
        cid = self.by_name.get(name.strip().strip("'").lower())
        return self.handed.get(cid) if cid else None

    def __len__(self) -> int:
        return len(self.handed)


# ---------- the numeral guard ----------
# A figure in prose: 12 / 1,234 / 16.04 / 16% / 5.0M / 10.9bn / 1,000. Not part of a name (CAL04), a date (2026-09-25),
# a time (06:00), a version (0.1.0) or an ordinal (1st): the lookbehind and lookahead keep those out.
_ANSWER_NUM = re.compile(r"(?<![\w.,:/'\-])([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(\s?(?:%|bn|k|m|b))?(?![\w.,:/'\-]*\w)", re.I)
# A figure in a source, with the k/M/bn a compact rendering carries (the material writes `CAL03 Opex: 30.1M`): the suffix
# counts only as a whole word, so `5 models` is five and `3 bn` is three billion.
_ANY_NUM = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:\s?(bn|k|m|b)(?![\w]))?", re.I)
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9}
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_OPS = re.compile(r"[+\-×x*/÷=]|\bof\b|\bis\b|\btotal\b|\bsum\b|\bacross\b|\bcombined\b|\btogether\b")
# A code span that is only numbers, units and arithmetic (`5,017,824`, `16.0%`, `593,711 + 593,711 = 1,187,422`) is a
# figure written in backticks, not a name: it is checked like prose. Anything with a letter beyond a unit suffix is a name.
_NUMERIC_SPAN = re.compile(r"`\s*([0-9][0-9,.\s%+\-*/=x×÷()kKmMbBn£$€]*(?:\s?(?:ms|s|min|h|hrs|d|cells|rows|items))?)`")
# The number of a heading (`### 3.2 Proposed line items`) or of a list item (`12. Reconcile`) is structure, not a figure.
_HEADING_NUM = re.compile(r"^(\s{0,3}#{1,6}\s+)\d+(?:\.\d+)*\.?\s", re.M)
_LIST_MARK = re.compile(r"^(\s*)\d+\.\s", re.M)


def strip_code(text: str) -> str:
    """Prose only: fenced blocks and code spans (formulas, object names, ids) are not figures."""
    return _CODE.sub(" ", text or "")


def numbers_in(text: str) -> list[float]:
    """Every figure in a source, a compact one (30.1M, 666K, 10.9bn) multiplied out."""
    out = []
    for m in _ANY_NUM.finditer(text or ""):
        suf = (m.group(1) or "").lower()
        raw = m.group(0)[: -len(suf)] if suf else m.group(0)
        try:
            out.append(float(raw.replace(",", "").strip()) * _MULT.get(suf, 1.0))
        except ValueError:
            pass
    return out


def _near(sorted_vals: list[float], cand: float, tol: float) -> bool:
    i = bisect.bisect_left(sorted_vals, cand - tol - 1e-9)
    return i < len(sorted_vals) and sorted_vals[i] <= cand + tol + 1e-9


def _derivable(v: float, tol: float, others: list[float], cap: int = 40) -> bool:
    """v equals a sum, difference, product, quotient or percentage share of two other figures in the answer, or the total of
    three or four of them (an estate's cells are the four models' cells added up)."""
    xs = others[:cap]
    for i, a in enumerate(xs):
        for b in xs[i + 1:]:
            cands = [a + b, a - b, b - a, a * b]
            if b:
                cands += [a / b, a / b * 100]
            if a:
                cands += [b / a, b / a * 100]
            if any(abs(c - v) <= tol for c in cands):
                return True
    ys = sorted(set(xs), reverse=True)[:30]
    for r in (3, 4):
        if any(abs(sum(combo) - v) <= tol for combo in combinations(ys, r)):
            return True
    return False


def figures(text: str, sources: list[str]) -> dict:
    """Every figure in the answer's prose, sorted: traced (it appears in a source, allowing the rounding the answer shows,
    a percentage written as a fraction or the reverse, and k/M/bn suffixes), derived (arithmetic shown nearby over other
    figures in the answer, or a total over up to four of them), benign (a small count up to ten, a year) or untraced.
    Heading and list numbers are structure, not figures. Returns the untraced ones as written so the page can mark them."""
    S = sorted({v for s in sources for v in numbers_in(s or "")})
    numeric_spans = [m.group(1).strip() for m in _NUMERIC_SPAN.finditer(text or "") if re.search(r"\d", m.group(1))]
    prose = _LIST_MARK.sub(r"\1", _HEADING_NUM.sub(r"\1", strip_code(text)))
    prose += "\n" + " ; ".join(numeric_spans) if numeric_spans else ""
    found = []
    for m in _ANSWER_NUM.finditer(prose):
        raw, suf = m.group(1), (m.group(2) or "").strip().lower()
        try:
            base = float(raw.replace(",", ""))
        except ValueError:
            continue
        d = len(raw.split(".")[1]) if "." in raw else 0
        mult = _MULT.get(suf, 1.0)
        found.append((m.group(0).strip(), base * mult, d, mult, suf == "%", m.start(), abs(base)))
    vals = [f[1] for f in found]
    out = {"checked": 0, "traced": 0, "derived": 0, "untraced": [], "benign": 0}
    for raw, v, d, mult, pct, pos, base in found:
        if not pct and mult == 1.0 and d == 0 and (base <= 10 or 1900 <= base <= 2100):
            out["benign"] += 1
            continue
        out["checked"] += 1
        tol = 0.5 * 10 ** (-d) * mult
        if any(_near(S, c, t) for c, t in ((v, tol), (-v, tol), (v / 100, tol / 100), (v * 100, tol * 100))):
            out["traced"] += 1
            continue
        window = prose[max(0, pos - 80): pos + len(raw) + 80]
        # the operands are usually beside the result: the figures around it come first, then the rest of the answer, so a
        # long handover with more figures than the cap still derives a share shown as `a / b = c%`
        near = [f[1] for f in found if abs(f[5] - pos) <= 160 and abs(f[1] - v) > tol]
        seen_near = set(near)
        pool = near + [x for x in vals if x != v and x not in seen_near]      # duplicates kept: a figure written twice may be doubled
        if _OPS.search(window) and _derivable(v, tol, pool):
            out["derived"] += 1
            continue
        if raw not in out["untraced"]:
            out["untraced"].append(raw)
    return out
