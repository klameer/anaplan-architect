"""The answer contract: every answer opens with a Brief the reader can decide from, and folds the rest under `##`
headings the page renders closed. The prompt says so; the renderer (web/src/objects.tsx foldSections) does the folding."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect.chat import CHAT_SYSTEM


def test_the_prompt_asks_for_a_brief_then_folded_sections():
    assert "## Brief" in CHAT_SYSTEM and "three to five sentences" in CHAT_SYSTEM
    assert "every other section closed under its heading" in CHAT_SYSTEM
    assert "A short question gets a Brief and nothing else" in CHAT_SYSTEM
    # the renderer folds on `##`, so the contract must not ask for any other heading level at the top
    assert "`##` headings" in CHAT_SYSTEM


def test_the_renderer_folds_on_second_level_headings():
    src = (pathlib.Path(__file__).resolve().parents[1] / "web" / "src" / "objects.tsx").read_text(encoding="utf-8")
    assert "function foldSections" in src and "tagName === 'H2'" in src and "details.sec" in src
    assert "foldSections(d, !!streaming)" in src


def test_the_prompt_every_workspace_gets_names_nothing_from_the_demo():
    """Review 2026-11-13, item 8: the instructions sent with every question, for every workspace, carried the demo's
    model, a demo module and its cell count as examples. Examples in the prompt are neutral."""
    import re, json
    from anaplan_architect import chat, opinion
    from anaplan_architect.tools import Toolbox
    import inspect
    text = chat.CHAT_SYSTEM + chat.CONCISE + opinion.SYSTEM + inspect.getsource(Toolbox.schema)          # the tool descriptions travel with every question too
    found = re.findall(r"Caldergate|\b(?:CAL|SYS|INP|OUT|DAT)\d\d\b|Finance Systems|70200000|59800000", text)
    assert not found, found

