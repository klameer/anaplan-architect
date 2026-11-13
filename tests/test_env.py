import sys, pathlib, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect import envfile


def test_env_file_sets_unset_keys_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ARCH_TEST_A", raising=False); monkeypatch.setenv("ARCH_TEST_B", "kept")
    f = tmp_path / ".env"; f.write_text('# comment\nARCH_TEST_A="from file"\nARCH_TEST_B=overwritten\n', encoding="utf-8")
    assert envfile.load([f]) == ["ARCH_TEST_A"]
    assert os.environ["ARCH_TEST_A"] == "from file" and os.environ["ARCH_TEST_B"] == "kept"
