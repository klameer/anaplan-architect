"""Read a .env file into os.environ without a dependency. Looked up in
this order, first found wins per key, and a value already in the
environment is never overwritten:

  ./.env                       the current directory
  <repo>/.env                  next to pyproject.toml, two levels above this package
  ~/.anaplan-architect.env     the user's home

Lines are KEY=value; quotes around the value are stripped; # starts a comment.
"""
from __future__ import annotations
import os
from pathlib import Path


def candidates() -> list[Path]:
    here = Path(__file__).resolve()
    return [Path.cwd() / ".env", here.parents[2] / ".env", Path.home() / ".anaplan-architect.env"]


def load(paths: list[Path] | None = None) -> list[str]:
    """Returns the keys set."""
    set_keys = []
    for p in paths or candidates():
        if not p.is_file():
            continue
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, _, v = ln.partition("=")
            k = k.strip(); v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            if k and k not in os.environ:
                os.environ[k] = v; set_keys.append(k)
    return set_keys
