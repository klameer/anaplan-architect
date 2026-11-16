"""What to ask next. Answers are short on purpose, so the depth is in the second and third question: under every
answer are two or three questions that lead from the feature it showed into another one (a why into a plan, a
calculation into its reach, a reach into the documents).

They are made by code. Each kind of answer has its next questions, filled with the object the answer was about: the
line item the formula block drew, the selection the reach was read from, the object the documents were followed
from. So they cost no model call and can never name something the model does not have.
"""
from __future__ import annotations

KINDS = ("why", "calculation", "plan", "overview", "improve", "implications", "documents", "count", "general")

# (the feature it leads to, the question, needs: None | "subject" | "line_item"); {x} is the object the answer was about
_NEXT = {
    "why": [("calculation", "How is {x} calculated?", "line_item"), ("plan", "Give me a plan to change {x}.", "subject"),
            ("implications", "What are the implications of changing {x}?", "subject"), ("documents", "What do the project documents say about {x}?", "subject")],
    "calculation": [("why", "Why is {x} built this way?", "subject"), ("implications", "What are the implications of changing {x}?", "subject"),
                    ("documents", "What do the project documents say about {x}?", "subject")],
    "plan": [("implications", "What are the implications of changing {x}?", "subject"), ("general", "Explain the Planual flags on this plan.", "flags"),
             ("general", "What should I check once this is built?", None), ("why", "Why is {x} built the way it is today?", "subject")],
    "overview": [("improve", "What should we fix first, and what has already been decided?", None), ("general", "Which modules should a new builder read first, and why?", None),
                 ("general", "Which feeds between the models are confirmed, and which are only inferred?", None)],
    "improve": [("plan", "Give me a plan for the first fix.", None), ("implications", "What are the implications of changing {x}?", "subject"),
                ("why", "Why is {x} built this way?", "subject")],
    "implications": [("general", "What should I test before changing {x}?", "subject"), ("documents", "What do the project documents say about {x}?", "subject"),
                     ("why", "Why is {x} built this way?", "subject"), ("calculation", "How is {x} calculated?", "line_item")],
    "documents": [("why", "Why is {x} built this way?", "subject"), ("implications", "What are the implications of changing {x}?", "subject"),
                  ("calculation", "How is {x} calculated?", "line_item")],
    "count": [("general", "Which of these hold the most cells?", None), ("improve", "What should we fix first?", None)],
    "general": [("implications", "What are the implications of changing {x}?", "subject"), ("why", "Why is {x} built this way?", "subject")],
}
# nobody wrote the reason down: the next step is to look wider, not to ask why again
_NOT_RECORDED = [("documents", "What do the project documents say about {x}?", "subject"), ("implications", "What are the implications of changing {x}?", "subject"),
                 ("calculation", "How is {x} calculated?", "line_item")]


def suggest(kind: str, subject: dict | None, flags: int = 0, not_recorded: bool = False, limit: int = 3) -> list[dict]:
    """Up to three next questions for an answer of this kind about this object ({"kind": "line_item" | "module", "ref"}).
    A question that needs an object is left out when the answer had none; one about a formula is left out for a module."""
    rows = _NOT_RECORDED if not_recorded else _NEXT.get(kind) or _NEXT["general"]
    out: list[dict] = []
    for leads_to, text, needs in rows:
        if needs in ("subject", "line_item") and not (subject and subject.get("ref")):
            continue
        if needs == "line_item" and subject.get("kind") != "line_item":
            continue
        if needs == "flags" and not flags:
            continue
        out.append({"text": text.format(x=subject["ref"]) if subject else text, "leads_to": leads_to})
        if len(out) >= limit:
            break
    return out


def subject_of(blocks: list[dict], cited: list[dict], text: str = "") -> dict | None:
    """The object an answer was about: the one its own figure was drawn for, else the first line item or module it
    cites in its lead. Always an object a tool handed, so always one the model has."""
    for b in blocks:
        if b.get("type") == "calculation" and b.get("ref"):
            return {"kind": "line_item", "ref": b["ref"], "model": b.get("model")}
        if b.get("type") == "reach" and b.get("ref"):
            return {"kind": "line_item" if "." in str(b["ref"]) and b.get("kind") != "module" else "module", "ref": b["ref"], "model": b.get("model")}
        if b.get("type") == "object_documents" and b.get("object"):
            return {"kind": b.get("kind") or ("line_item" if "." in b["object"] else "module"), "ref": b["object"], "model": b.get("model")}
        if b.get("type") == "build_plan":
            p = b.get("plan") or {}
            ch = (p.get("changes") or [None])[0]
            if ch:
                return {"kind": "line_item", "ref": f"{ch['module']}.{ch['name']}", "model": p.get("model")}
            used = ((p.get("uses") or {}).get("line_items") or [None])[0]
            if used:
                return {"kind": "line_item", "ref": f"{used['module']}.{used['name']}", "model": p.get("model")}
    objs = [c for c in cited if c.get("kind") in ("line_item", "module") and c.get("ref")]
    if not objs:
        return None
    pos = lambda c: (text.find("`" + c["ref"] + "`") if "`" + c["ref"] + "`" in text else 10 ** 9)
    first = sorted(objs, key=lambda c: (pos(c), c["kind"] != "line_item"))[0]
    return {"kind": first["kind"], "ref": first["ref"], "model": first.get("model")}
