"""One document: the opinion first, the deterministic estate report behind it."""
from __future__ import annotations
import datetime
from anaplan_estate.fleet import render_markdown as render_estate
from .store import Workspace
from .opinion import Opinion, render_markdown as render_opinion


def render_review(w: Workspace, op: Opinion | None, title: str = "", signed_by: str = "") -> str:
    er = w.estate
    out = [f"# Architect's review: {title or ', '.join(m.name for m in er.models)}", "",
           f"Generated {datetime.date.today().isoformat()}. "
           + (f"Signed: {signed_by}." if signed_by else "Unsigned: no interviews, no materiality agreed with the owner, no check against design documents. A signed review adds those."), "",
           "## How to read this", "",
           "Two parts. **The opinion** is written by a reviewer from the estate facts: strengths, the decisions that explain the build, which patterns matter, risks, options, "
           "the handover page and questions. Every claim cites the objects it rests on and a validator removed any claim naming an object the estate does not contain. "
           "**The estate report** behind it is deterministic: every number computed from the exports, no judgement. "
           + (f"{len(w.statuses)} pattern(s) carry an owner status and {len(w.memories)} owner note(s) were taken into account." if (w.statuses or w.memories) else ""), ""]
    if op:
        by = op.by_kind()
        first = by["handover"][:1] + by["design_decision"][:2] + by["materiality"][:2] + by["risk"][:1]
        if first:
            out += ["## What the reviewer would say first", ""]
            for o in first:
                out.append(f"- **{o.title}.** {o.claim.split('. ')[0]}.")
            out.append("")
    out += ["---", "", render_opinion(op) if op else "_No opinion generated. Run `anaplan-architect review --run` with a key, or `--prompt` then `--response`._", "", "---", "",
            render_estate(er)]
    return "\n".join(out)
