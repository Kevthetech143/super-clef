#!/usr/bin/env python3
"""Speed PR 1: memory calls answered in-process, the ssh master kept 4h without outliving a host change,
secret verdicts kept per file sha. Made-up notes; no network.

    python3 -m pytest skills/super-jev/tests/test_speed1.py -q
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SKILL / "lib"))
spec = importlib.util.spec_from_file_location("ask_speed1", SKILL / "ask.py")
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)
import clef_client  # noqa: E402
import dispatch  # noqa: E402

REQUESTS = [{"action": "panel", "principal": "me"},
            {"action": "cached", "principal": "me", "question": "where is the boiler manual"},
            {"action": "search", "pointer": "none", "principal": "me", "question": "q"},
            {"action": "sources"}, {"action": "nonsense"}]


@pytest.fixture
def memory_state(tmp_path, monkeypatch):
    (tmp_path / "_memory").mkdir()
    (tmp_path / "_memory" / "config.json").write_text(json.dumps({"db": "mem.sqlite", "registry": "reg.json"}))
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SUPERJEV_REPO", raising=False)
    return tmp_path


def _norm(out):
    return {k: v for k, v in out.items() if k != "attemptId"}


def test_memory_makes_no_subprocess_and_answers_like_the_old_process(memory_state, monkeypatch):
    old = []
    for req in REQUESTS:
        r = subprocess.run([sys.executable, str(SKILL / "dispatch.py"), "memory", "--input", "/dev/stdin"],
                           input=json.dumps(req), capture_output=True, text=True)
        old.append(_norm(json.loads(r.stdout)))

    def boom(*a, **k):
        raise AssertionError(f"memory spawned a process: {a}")
    monkeypatch.setattr(ask.subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    assert [_norm(ask.memory(dict(r))) for r in REQUESTS] == old


def test_memory_without_setup_answers_not_set_up_in_process(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("SUPERJEV_REPO", raising=False)
    monkeypatch.setattr(ask.subprocess, "run", lambda *a, **k: pytest.fail("spawned"))
    out = ask.memory({"action": "panel", "principal": "me"})
    assert out["reason"] == "not-set-up"


def test_a_secret_request_is_still_never_sent(memory_state):
    with pytest.raises(ask.SecretHeld):
        ask.memory({"action": "cached", "principal": "me", "question": "api_key = sk-live-" + "a1B2c3D4e5" * 4})


def test_memory_keeps_the_callers_umask(memory_state):
    import os
    before = os.umask(0o022)
    try:
        ask.memory({"action": "panel", "principal": "me"})
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(before)


# --- secret verdicts per sha ---------------------------------------------------------------------
def _setup_scan(tmp_path, monkeypatch, name="me"):
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path / "state"))
    ask._SCAN.update(path=None, rows={}, dirty=False)  # a new process
    ask.use_scan_cache(name)


def test_scan_runs_once_per_sha_and_again_when_the_file_changes(tmp_path, monkeypatch):
    _setup_scan(tmp_path, monkeypatch)
    calls = []
    real = ask.clean_text
    monkeypatch.setattr(ask, "clean_text", lambda t, p: calls.append(1) or real(t, p))
    clean = "# Boiler\nThe manual is in the blue binder.\n"
    dirty = "# Boiler\napi_key = sk-live-" + "a1B2c3D4e5" * 4 + "\n"
    f = tmp_path / "boiler.md"
    f.write_text(clean)
    assert ask.text_can_leave(str(f), f.read_bytes(), clean) is True
    assert ask.text_can_leave(str(f), f.read_bytes(), clean) is True
    assert len(calls) == 1
    ask.flush_scan_cache()
    ask._SCAN.update(path=None, rows={}, dirty=False)  # next ask, new process: read back from the state dir
    ask.use_scan_cache("me")
    assert ask.text_can_leave(str(f), clean.encode(), clean) is True
    assert len(calls) == 1
    f.write_text(dirty)
    assert ask.text_can_leave(str(f), dirty.encode(), dirty) is False
    assert len(calls) == 2
    assert ask.text_can_leave(str(f), dirty.encode(), dirty) is False
    assert len(calls) == 2


def test_cache_holds_no_file_text_and_is_dropped_when_the_rules_change(tmp_path, monkeypatch):
    _setup_scan(tmp_path, monkeypatch)
    text = "# Boiler\nsecretword-in-a-made-up-note\n"
    ask.text_can_leave(str(tmp_path / "a.md"), text.encode(), text)
    ask.flush_scan_cache()
    saved = Path(ask._SCAN["path"])
    assert "secretword" not in saved.read_text()
    assert (saved.stat().st_mode & 0o777) == 0o600
    ask._SCAN.update(path=None, rows={}, dirty=False, fp="other-rules")
    ask.use_scan_cache("me")
    assert ask._SCAN["rows"] == {}
    ask._SCAN["fp"] = None


def test_held_files_are_the_same_with_and_without_the_cache(tmp_path, monkeypatch):
    root = tmp_path / "notes"
    root.mkdir()
    ok, bad, big = root / "ok.md", root / "bad.md", root / "plain.md"
    texts = {ok: "# Ok\nedited but fine\n", bad: "# Bad\npassword = hunter2hunter2\napi_key = sk-live-" + "a1B2c3D4e5" * 4 + "\n",
             big: "# Plain\nunchanged\n"}
    cache = {}
    for f, t in texts.items():
        f.write_text(t)
        cache[str(f)] = {"sha256": hashlib.sha256(t.encode()).hexdigest(), "pass": True, "local": True}
    ok.write_text(texts[ok] + "more\n")
    bad.write_text(texts[bad] + "more\n")
    monkeypatch.setattr(ask, "load_cache_files", lambda ptr: cache)
    monkeypatch.setattr(ask.auto_heal, "_report_for", lambda *a, **k: ({}, None))
    _setup_scan(tmp_path, monkeypatch)
    monkeypatch.setattr(ask, "use_stat_memo", lambda p: None)
    ask._ACTIVE_MEMO[0] = None
    with_cache = [ask.edited_held(["p1"]) for _ in range(2)]
    ask._SCAN.update(path=None, rows={}, dirty=False)  # no cache: every file scanned, as before
    without = ask.edited_held(["p1"])
    assert with_cache[0] == with_cache[1] == without
    assert without["secret"] == [str(bad)]


# --- ssh master ----------------------------------------------------------------------------------
def _fake_ssh(monkeypatch, tmp_path):
    import tempfile
    home = Path(tempfile.mkdtemp(prefix="h", dir="/tmp"))  # short: a long HOME would move the socket folder
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(clef_client, "SHORT_DIR", str(home / "scl"))
    monkeypatch.setattr(sys.modules[__name__], "HOME", home, raising=False)
    ran = []
    monkeypatch.setattr(clef_client.subprocess, "run", lambda cmd, **k: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    return ran


def test_master_is_kept_four_hours_with_the_same_safe_path(tmp_path, monkeypatch):
    _fake_ssh(monkeypatch, tmp_path)
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "user@made-up-host")
    cmd = clef_client._ssh_cmd("true")
    assert "ControlPersist=4h" in cmd and "ControlPersist=600" not in cmd
    cp = next(a for a in cmd if a.startswith("ControlPath="))
    assert cp == f"ControlPath={HOME}/.ssh/cm-superclef-%C"
    assert ((HOME / ".ssh").stat().st_mode & 0o777) == 0o700
    assert cmd[-2:] == ["user@made-up-host", "true"]


def test_a_changed_host_closes_the_old_master_once(tmp_path, monkeypatch):
    ran = _fake_ssh(monkeypatch, tmp_path)
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "user@host-a")
    clef_client._ssh_cmd("true")
    clef_client._ssh_cmd("true")
    assert ran == []  # first use and same host: nothing to close
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "user@host-b")
    clef_client._ssh_cmd("true")
    clef_client._ssh_cmd("true")
    assert len(ran) == 1 and ran[0][-3:] == ["-O", "exit", "user@host-a"]
    assert any(a.startswith("ControlPath=") and a.endswith("cm-superclef-%C") for a in ran[0])


def test_symlinked_socket_folder_is_still_refused(tmp_path, monkeypatch):
    _fake_ssh(monkeypatch, tmp_path)
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "user@made-up-host")
    (tmp_path / "elsewhere").mkdir(mode=0o700)
    (HOME / ".ssh").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(clef_client.Unreachable):
        clef_client._ssh_cmd("true")
