#!/usr/bin/env python3
"""First run under Super Clef: an empty prepare-cache says what to do and is not a pointer failure.
Offline: memory is a stub, the state is made up, the judge is never called.

    python3 -m pytest skills/super-jev/tests/test_first_run_no_cache.py -q
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
spec = importlib.util.spec_from_file_location("ask_first_run", SKILL / "ask.py")
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)
ah = ask.auto_heal


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    ask._STAGE.clear()
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fake(req):
        if req["action"] == "panel":
            return {"pointers": [{"pointer": "notes-1"}]}
        calls.append(req["action"])
        return {"status": "miss"}
    monkeypatch.setattr(ask, "memory", fake)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(ah, "maybe_scan", lambda *a, **k: None)

    def go():
        rc = ask.lookup("what is the warranty period", "primary", tmp_path / "s")
        return rc, capsys.readouterr().out, calls
    yield go, tmp_path
    ask._STAGE.clear()


def test_empty_cache_says_import_state_and_no_pointer_failure(run):
    go, tmp = run
    rc, out, calls = go()
    assert "run: superclef import-state --from-superjev" in out
    assert "or reconnect" in out
    assert ask._RESULT["outcome"] == "needs-setup" and ask._RESULT["next"] == "refresh"
    assert ask._RESULT["cmd"] == "superclef import-state --from-superjev"
    assert [r["state"] for r in ask._RESULT["unsearched"]] == ["unprepared"]
    assert not ask._RESULT["errors"]
    assert "navigate" not in calls
    health = tmp / "s" / "pointer_health.json"
    assert not health.exists() or "notes-1" not in json.loads(health.read_text())


def test_cache_present_does_not_take_the_first_run_path(run):
    go, tmp = run
    (tmp / "cache").mkdir()
    (tmp / "cache" / "other.json").write_text("{}")
    go()
    assert ask._RESULT.get("why") != "nothing has been prepared yet (empty prepare-cache)"
