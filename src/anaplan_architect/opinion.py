"""The architect's opinion: a model reads the estate material and writes
what a senior reviewer writes in the first day. Every claim cites objects
the deterministic layer produced; a validator drops or demotes anything
that names an object the estate does not contain.

Kinds:
  strength          what is done well, with evidence (three to five)
  design_decision   the decisions that explain how the estate is built, and what each costs and buys
  materiality       per pattern or family of patterns: deliberate or accidental, matters or not, why
  risk              key-person, calculation, size, change, integration risks, each with evidence
  option            hygiene (days) | restructure (weeks) | rebuild (quarter): what it fixes, what it risks, cells/effort/blast radius
  automation        what a deterministic process should own; where an assistant helps; what neither should touch
  handover          the page the next builder reads first: purpose, five modules to read, three decisions, traps
  question          what you would ask the owner in the first hour, ranked by what it unblocks

Refs cite: a model name; "Module"; "Module.Line Item"; "Model :: Module.Line Item" when the name exists in several models;
"action:Name"; "finding:RULE"; "pattern:<id>" exactly as listed in the material.
"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field, asdict
from .store import Workspace

KINDS = ["strength", "design_decision", "materiality", "risk", "option", "automation", "handover", "question"]

SYSTEM = """You are a senior Anaplan solution architect with fifteen years of FP&A and planning-system work, reviewing an estate you have never seen from its deterministic facts. You are pragmatic: a formula that breaks a rule may be doing its job, and you say so when it is. You write for the estate's owner: plain, specific, no flattery, no hedging, short sentences, no em dashes. You never invent an object. Every claim cites the models, modules, line items, actions, findings or patterns it rests on, exactly as named in the material. If the material does not support a claim, you ask a question instead of asserting."""

INSTRUCTIONS = """Produce a JSON array of observations. Each observation:
{"kind": one of strength | design_decision | materiality | risk | option | automation | handover | question,
 "title": short noun phrase,
 "claim": two to six sentences, specific, citing objects by their exact names,
 "refs": ["FP&A", "Module", "Module.Line Item", "action:Name", "finding:RULE-ID", "pattern:<id>"] exact names from the material,
 "effort": for options only: "days" | "weeks" | "quarter",
 "cost": for options only: what it saves in cells, effort share, or modules touched, from the material,
 "priority": 1 (do first) to 5}

Cover, in this order:
- strength: three to five things done well, each with evidence.
- design_decision: the five to eight decisions that explain how the estate is built (how the models split, dimensional strategy, currency and versions, how summaries and reports are produced, how data enters and leaves). What each costs and buys.
- materiality: for each of the ten largest patterns or families of patterns: deliberate or accidental, matters or not for this estate, and why. Be willing to say a rule break does not matter.
- risk: key-person, calculation, size, change and integration risks with the evidence.
- option: hygiene (days), restructure (weeks), rebuild (quarter). Each with what it fixes, what it risks, and its cost figure.
- automation: where a deterministic process replaces manual work; where an assistant helps; where neither should touch.
- handover: exactly one: the page the next builder reads first. Purpose of each model in a sentence, the five modules to read first and why, the three decisions that explain the shape, the traps.
- question: what you would ask the owner in the first hour, ranked by what it unblocks.

Between 25 and 40 observations. Refs must be exact. No markdown inside JSON strings. Respect any statuses and owner notes in the material: a pattern marked deliberate is not a finding."""

CRITIQUE = """Below are observations about an Anaplan estate, and the material they were written from. For each observation, check that every sentence is supported by the material and that every ref is an exact name from it. Rewrite any unsupported sentence to what the material does support, or remove it. Remove any ref that is not an exact name. Keep the JSON shape. Return the corrected JSON array only."""


@dataclass
class Observation:
    kind: str
    title: str
    claim: str
    refs: list[str]
    priority: int = 3
    effort: str = ""
    cost: str = ""
    valid_refs: list[str] = field(default_factory=list)
    dropped_refs: list[str] = field(default_factory=list)


@dataclass
class Opinion:
    observations: list[Observation]
    dropped: list[dict]
    provider: str

    def by_kind(self):
        out = {k: [] for k in KINDS}
        for o in self.observations:
            out[o.kind].append(o)
        return out

    def to_dict(self):
        return {"provider": self.provider, "observations": [asdict(o) for o in self.observations], "dropped": self.dropped}


def validate(obs: list[dict], w: Workspace) -> tuple[list[Observation], list[dict]]:
    idx = w.index()
    allrefs = set().union(*idx.values())
    lower = {r.lower(): r for r in allrefs}
    kept, dropped = [], []
    for o in obs:
        kind = o.get("kind", "question")
        if kind not in KINDS:
            kind = "question"
        refs = [str(r).strip() for r in o.get("refs", []) if str(r).strip()]
        ok, bad = [], []
        for r in refs:
            if r in allrefs:
                ok.append(r)
            elif r.lower() in lower:
                ok.append(lower[r.lower()])
            else:
                bad.append(r)
        title = str(o.get("title", ""))[:120]; claim = str(o.get("claim", "")).strip()
        if not claim:
            continue
        if bad and not ok:
            dropped.append({"title": title, "kind": kind, "reason": "no valid refs", "bad_refs": bad, "claim": claim[:200]}); continue
        if bad and len(bad) > len(ok):
            kind = "question"
        if not ok and kind != "question":
            kind = "question"
        kept.append(Observation(kind=kind, title=title, claim=claim, refs=refs, priority=int(o.get("priority", 3) or 3),
                                effort=str(o.get("effort", "") or ""), cost=str(o.get("cost", "") or ""), valid_refs=ok, dropped_refs=bad))
    kept.sort(key=lambda x: (KINDS.index(x.kind), x.priority, x.title))
    return kept, dropped


def _extract_json(text: str):
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("no JSON array in response")
    return json.loads(m.group(0))


def prompt(material: str) -> str:
    return SYSTEM + "\n\n" + INSTRUCTIONS + "\n\n# Material\n\n" + material


def ingest(w: Workspace, json_text: str, provider: str = "ingested") -> Opinion:
    kept, dropped = validate(_extract_json(json_text), w)
    return Opinion(kept, dropped, provider)


def run(w: Workspace, material: str, api_key: str, model_id: str = "claude-sonnet-5", critique: bool = True, client=None) -> Opinion:
    """Anthropic SDK, two passes, temperature 0. `client` may be injected (tests)."""
    if client is None:
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit("pip install anthropic, or use `review --prompt` then `review --response`") from e
        client = anthropic.Anthropic(api_key=api_key)

    # The material is the bulk of both passes; as a cached system block the critique pass reads it from cache.
    system = [{"type": "text", "text": SYSTEM},
              {"type": "text", "text": "# Material\n\n" + material, "cache_control": {"type": "ephemeral"}}]

    def ask(content):
        r = client.messages.create(model=model_id, max_tokens=12000, system=system, messages=[{"role": "user", "content": content}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")

    text = ask(INSTRUCTIONS + "\n\nThe material is in the system prompt.")
    if critique:
        text = ask(CRITIQUE + "\n\n# Observations\n\n" + text + "\n\nThe material is in the system prompt.")
    return ingest(w, text, provider=f"anthropic:{model_id}")


TITLES = {"strength": "What is done well", "design_decision": "How the estate is built, and what it costs",
          "materiality": "Which patterns matter", "risk": "Risk register", "option": "Options",
          "automation": "What to automate, and what not to", "handover": "The handover page", "question": "Questions for the owner"}


def render_markdown(op: Opinion) -> str:
    out = ["# Architect's opinion", "",
           f"Written by {op.provider} from the estate facts. Every claim cites objects the deterministic layer produced; "
           f"{len(op.dropped)} claim(s) were removed because they named objects the estate does not contain.", ""]
    for kind, obs in op.by_kind().items():
        if not obs:
            continue
        out += [f"## {TITLES[kind]}", ""]
        for o in obs:
            hdr = f"**{o.title}**"
            if o.kind == "option" and o.effort:
                hdr += f" ({o.effort}{', ' + o.cost if o.cost else ''})"
            if o.kind in ("risk", "option", "question"):
                hdr += f" · priority {o.priority}"
            out += [hdr, "", o.claim, "", "Evidence: " + ", ".join(f"`{r}`" for r in o.valid_refs)]
            if o.dropped_refs:
                out.append(f"(refs not found and removed: {', '.join(o.dropped_refs)})")
            out.append("")
    if op.dropped:
        out += ["## Removed by the validator", ""] + [f"- {d['title']} ({d['kind']}): {d['reason']} ({', '.join(d['bad_refs'])})" for d in op.dropped]
    return "\n".join(out)
