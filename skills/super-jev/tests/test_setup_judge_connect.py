#!/usr/bin/env python3
"""Offline tests for setup's judge-host check, its connect hint, and the connect-before-setup trap.

    python3 -m pytest skills/super-jev/tests/test_setup_judge_connect.py -q
"""
import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("setup_judge_under_test", SKILL / "setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "not-a-real-key")
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "judge@example-host")
    monkeypatch.setattr(setup, "_node_major", lambda: 24)
    monkeypatch.setattr(setup, "_python_version", lambda: (3, 12, 1))
    monkeypatch.setattr(setup, "_judge_reachable", lambda host: True)
    clef = dataclasses.replace(setup.judges.profile(), kind="clef")   # the suites default to the jev profile
    monkeypatch.setattr(setup.judges, "profile", lambda: clef)
    return tmp_path


def run(capsys):
    rc = setup.main([])
    return rc, capsys.readouterr().out


def test_unreachable_judge_says_how_to_set_the_host(env, capsys, monkeypatch):
    monkeypatch.setattr(setup, "_judge_reachable", lambda host: False)
    rc, out = run(capsys)
    assert rc == 1 and "NOT READY" in out
    assert "judge@example-host did not answer ssh" in out and "SUPERCLEF_CLEF_HOST=user@clef-host" in out and "SUPERJEV" not in out


def test_unset_judge_host_says_how_to_set_it(env, capsys, monkeypatch):
    monkeypatch.delenv("SUPERJEV_CLEF_HOST")
    rc, out = run(capsys)
    assert rc == 1 and "judge host is not set" in out and "export SUPERCLEF_CLEF_HOST=" in out


def test_ready_message_points_at_superclef_connect(env, capsys):
    rc, out = run(capsys)
    assert rc == 0 and "superclef connect /path/to/folder" in out
    assert "prepare_bulk" not in out and "AGENTS.md" not in out


def test_setup_accepts_a_state_dir_connect_wrote(env, capsys):
    st = env / "state"
    (st / "_memory").mkdir(parents=True)
    (st / "_memory" / "registry.json").write_text(json.dumps({"datasets": {}}))
    (st / "prepare-cache").mkdir()
    (st / "prepare-cache" / "notes.json").write_text("{}")
    (st / "me").mkdir()
    (st / "me" / "lookups.jsonl").write_text("")
    rc, out = run(capsys)
    assert rc == 0 and "REFUSED" not in out
    assert (st / "_memory" / "config.json").is_file()
    assert (st / "_memory" / "registry.json").is_file()   # connect's file is kept


def test_setup_still_refuses_a_folder_with_foreign_files(env, capsys):
    st = env / "state"
    st.mkdir()
    (st / "my-thesis.docx").write_text("x")
    rc, out = run(capsys)
    assert rc == 1 and "REFUSED" in out
