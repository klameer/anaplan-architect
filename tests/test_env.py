import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect import envfile


def test_env_file_sets_unset_keys_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCH_TEST_A", raising=False); monkeypatch.setenv("ARCH_TEST_B", "kept")
    f = tmp_path / ".env"; f.write_text('# comment\nARCH_TEST_A="from file"\nARCH_TEST_B=overwritten\n', encoding="utf-8")
    assert envfile.load([f]) == ["ARCH_TEST_A"]
    assert os.environ["ARCH_TEST_A"] == "from file" and os.environ["ARCH_TEST_B"] == "kept"


def test_a_trailing_note_is_not_part_of_the_value(tmp_path, monkeypatch):
    """A line uncommented from .env.example may still carry its note: the note is not the value. Quoted values are kept whole."""
    for k in ("ARCH_TEST_C", "ARCH_TEST_D", "ARCH_TEST_E", "ARCH_TEST_F"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / ".env"
    f.write_text('ARCH_TEST_C=medium       # low | medium | high\nARCH_TEST_D="kept # whole"\nARCH_TEST_E=          # nothing yet\nARCH_TEST_F=a#b\n', encoding="utf-8")
    envfile.load([f])
    assert os.environ["ARCH_TEST_C"] == "medium" and os.environ["ARCH_TEST_D"] == "kept # whole"
    assert os.environ["ARCH_TEST_E"] == "" and os.environ["ARCH_TEST_F"] == "a#b"


def test_env_example_names_every_variable_the_providers_read():
    """A stranger with any of the five kinds of model has a line to copy: every variable the provider code reads from the
    environment is in .env.example, and so is every provider name. Read from the code, not from the README."""
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    example = (root / ".env.example").read_text(encoding="utf-8")
    from anaplan_architect import provider
    read = set()
    for name in ("provider.py", "codex.py", "openai_compat.py"):
        src = (root / "src" / "anaplan_architect" / name).read_text(encoding="utf-8")
        code = src.split('"""', 2)[2] if src.startswith('"""') else src            # the code, not the module's own description
        read |= set(re.findall(r'(?:env|environ\.get|getenv)\(\s*"([A-Z][A-Z0-9_]+)"', code))
    assert {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "AWS_REGION", "ARCHITECT_PROVIDER"} <= read
    read.discard("AWS_DEFAULT_REGION")                                             # the AWS fallback name for AWS_REGION, which is the one to set
    named = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, flags=re.M))
    assert not read - named, f".env.example lacks {sorted(read - named)}"
    line = next(ln for ln in example.splitlines() if ln.startswith("# Which block to use"))
    assert all(p in line for p in provider.PROVIDERS)
