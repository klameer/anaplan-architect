"""The tests, as the architect shows them. anaplan-estate keeps one numbered catalogue (its checks.py: every test
the engine runs, in six areas) and works out the result of each on a parse: found, clear, or not run and why. This
module adds nothing to that: it hands the rows on with the rules behind each test and the findings it produced
named, rolls them up by area for Home, and names the tests a rule or a plan card belongs to.

A test that found something is an observation or a review candidate, never a verdict. Clear means the pattern was
not found in these exports. Not run means an export or a column the test needs was not supplied: never that the
model is clear.
"""
from __future__ import annotations
from anaplan_estate import checks as echecks

STATUSES = ("found", "clear", "not run")
NOTE = ("a test that found something is an observation or a review candidate, never a verdict; clear means the pattern was not found "
        "in these exports; not run means an export or column the test needs is missing, never that the model is clear")


def results(er) -> list[dict]:
    """One row per test of the catalogue, in its order: the engine's result, the lint rules behind it, what it needs, and
    the findings it produced by id, title and model."""
    fmap = {f.id: f for f in er.findings}
    rows = []
    for r in echecks.results(er):
        c = echecks.BY_KEY[r["key"]]
        rows.append(dict(r, rules=list(c.rules), needs=[echecks.NEEDS_TEXT[n] for n in c.needs], planual=list(c.planual),
                         findings=[{"id": i, "title": fmap[i].title, "model": fmap[i].model} for i in r["findings"] if i in fmap]))
    return rows


def of(w) -> list[dict]:
    """The rows for a workspace's parse, worked out once: they depend on nothing but the parse."""
    rows = w.__dict__.get("_tests")
    if rows is None:
        rows = w.__dict__["_tests"] = results(w.estate)
    return rows


def _count(rows: list[dict]) -> dict:
    return {"total": len(rows), "found": sum(1 for r in rows if r["status"] == "found"), "clear": sum(1 for r in rows if r["status"] == "clear"),
            "not_run": sum(1 for r in rows if r["status"] == "not run")}


def areas(rows: list[dict]) -> list[dict]:
    return [dict({"num": cat.num, "key": cat.key, "title": cat.title, "blurb": cat.blurb}, **_count([r for r in rows if r["category"] == cat.num]))
            for cat in echecks.CATEGORIES]


def rollup(rows: list[dict]) -> dict:
    """What Home draws: the totals and one line per area."""
    return dict(_count(rows), areas=areas(rows))


def named(nums) -> list[dict]:
    """Test numbers as number and title, in catalogue order; a number the catalogue does not hold is dropped."""
    return [{"num": n, "title": echecks.BY_NUM[n].title} for n in nums or [] if n in echecks.BY_NUM]


def for_rule(rule: str) -> list[dict]:
    """The tests a lint rule (or a finding tag) belongs to."""
    return named(echecks.for_rules([rule]))


def handles() -> set[str]:
    """What an answer may write in backticks when it talks about the tests without naming an object of the estate: a
    test by its key, as test:<number>, or by its title (with or without its number); an area by its title (with or
    without its number); and the exports and columns a test needs. Lower case. The caller drops any that the estate
    really uses as the name of an object, so a handle never hides one."""
    out = {"test:" + c.num for c in echecks.CHECKS}
    for c in echecks.CHECKS:
        out |= {c.key.lower(), c.title.lower(), f"{c.num} {c.title}".lower(), f"test {c.num}"}
    for cat in echecks.CATEGORIES:
        out |= {cat.key.lower(), cat.title.lower(), f"{cat.num} {cat.title}".lower(), f"{cat.num}. {cat.title}".lower()}
    for v in echecks.NEEDS_TEXT.values():
        v = v.lower()
        bare = v.removeprefix("the ")
        out |= {v, bare, bare.removesuffix(" column")}
    return out | {"line items export"}
