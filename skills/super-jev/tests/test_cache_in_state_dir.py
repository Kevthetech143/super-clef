#!/usr/bin/env python3
"""The prepare-cache lives in the Super Clef state dir, so a new release keeps it. Offline, made-up state.

    python3 -m pytest skills/super-jev/tests/test_cache_in_state_dir.py -q --basetemp=/tmp/sc-r3c
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
import watched  # noqa: E402

spec = importlib.util.spec_from_file_location("ask_cache_state", SKILL / "ask.py")
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)


def test_cache_dir_follows_state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path / "st"))
    assert watched.state_cache_dir() == tmp_path / "st" / "prepare-cache"


def test_release_swap_keeps_the_cache_and_old_in_tree_cache_is_copied_once(tmp_path):
    state = tmp_path / "st" / "prepare-cache"
    old1 = tmp_path / "rel1" / "prepare-cache"
    old1.mkdir(parents=True)
    (old1 / "notes.json").write_text('{"/x/a.md": {"pass": true}}')
    assert watched.migrate_cache(state, old1) == 1
    assert json.loads((state / "notes.json").read_text()) == {"/x/a.md": {"pass": True}}
    (state / "notes.json").write_text('{"newer": 1}')  # a later change in the state dir is never overwritten
    assert watched.migrate_cache(state, old1) == 0
    assert json.loads((state / "notes.json").read_text()) == {"newer": 1}
    # a new release checkout has no in-tree cache at all: the state dir's cache is still there
    assert watched.migrate_cache(state, tmp_path / "rel2" / "prepare-cache") == 0
    assert (state / "notes.json").is_file()


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    ask._STAGE.clear()
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", tmp_path / "cache")
    calls = []

    def fake(req):
        if req["action"] == "panel":
            return {"pointers": [{"pointer": "notes"}, {"pointer": "docs"}]}
        calls.append(req["action"])
        return {"status": "miss"}
    monkeypatch.setattr(ask, "memory", fake)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(ask.auto_heal, "maybe_scan", lambda *a, **k: None)

    def go():
        ask.lookup("what is the warranty period", "primary", tmp_path / "s")
        return capsys.readouterr().out, calls
    yield go, tmp_path
    ask._STAGE.clear()


def test_missing_cache_prints_the_fix_and_benches_nothing(run):
    go, tmp = run
    out, calls = go()
    assert "run: superclef import-state --from-superjev, or reconnect" in out
    assert "navigate" not in calls
    health = tmp / "s" / "pointer_health.json"
    assert not health.exists() or not json.loads(health.read_text())


def test_first_upgrade_copies_the_cache_of_the_checkout_the_launcher_names(tmp_path, monkeypatch):
    rel = tmp_path / "release-old"
    (rel / "skills/super-jev/prepare-cache").mkdir(parents=True)
    (rel / "skills/super-jev/prepare-cache/notes.json").write_text("{}")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "superclef").write_text(f'#!/usr/bin/env bash\nexec node "{rel}/bin/superclef.js" "$@"\n')
    monkeypatch.setenv("SUPERJEV_BIN_DIR", str(bindir))
    monkeypatch.setattr(watched, "HERE", tmp_path / "newrel")
    state = tmp_path / "st" / "prepare-cache"
    assert watched.migrate_cache(state) == 1
    assert (state / "notes.json").is_file()
    assert watched.migrate_cache(state) == 0
