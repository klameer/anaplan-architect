"""For every test in the suite: the machine's own settings stay out.

The app reads `.env` at start (envfile.load) and builds its tracer and model client from what it finds. On a machine
whose `.env` holds a real LangSmith or model key, a test that builds the app would otherwise trace its fixture turns
to a real project, or call a real model. No test may do either: nothing here reads a `.env`, and the keys are taken
out of the environment before each test. A test that wants a tracer or a client passes a fake one in."""
import sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

KEYS = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT", "LANGSMITH_TRACE_CONTENT", "LANGSMITH_TRACE_MATERIAL",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "ARCHITECT_BASE_URL", "ARCHITECT_API_KEY",
        "ARCHITECT_HOSTED", "ARCHITECT_OPEN", "ARCHITECT_ADMIN_USER", "ARCHITECT_ADMIN_PASSWORD", "ARCHITECT_DEMO", "ARCHITECT_NOTICE", "ARCHITECT_MAX_UPLOAD_MB")


@pytest.fixture(autouse=True)
def _the_machines_settings_stay_out(monkeypatch):
    from anaplan_architect import envfile
    from anaplan_architect.orac import telemetry
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(telemetry, "_default", None)          # the process-wide tracer is rebuilt from this clean environment
    yield
