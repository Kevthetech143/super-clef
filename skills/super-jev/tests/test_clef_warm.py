#!/usr/bin/env python3
"""The warm clef daemon: single-instance lock, idle-exit logic, fallback to the one-shot path, and the payload
cleanup contract, all offline with a fake daemon on a unix socket (no clef machine, no model). One live test runs only
with SUPERJEV_TEST_LIVE=1.

    python3 -m pytest skills/super-jev/tests/test_clef_warm.py -q
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import clef_client  # noqa: E402
import clefd  # noqa: E402
import judge_profile  # noqa: E402

CLEF = judge_profile.load("clef")
REPLY = {"answers": {"pick": {"type": "choice", "choice": "a", "confidence": 0.9, "probabilities": {"a": 0.9, "b": 0.1}}},
         "model": "clef-flash", "usage": {"input_tokens": 50}}
Q = {"pick": {"type": "choice", "instructions": "which", "criteria": {"a": "x", "b": "y"}}}


@pytest.fixture
def home():
    import shutil
    h = tempfile.mkdtemp(dir="/tmp", prefix="cw")  # short path: unix socket paths are limited to ~104 bytes
    os.makedirs(os.path.join(h, ".clefd"), mode=0o700)
    yield h
    shutil.rmtree(h, ignore_errors=True)


def _fake_daemon(home, judge, idle=30):
    srv = clefd.bind(clefd.paths(home)[1])

    def run():
        try:
            clefd.serve(srv, judge, home, idle)
        finally:
            srv.close()  # like the real daemon: on Linux a still-listening socket keeps accepting into its backlog, so the
            # stop poll in the warm script would block in connect() forever instead of seeing the daemon gone
    th = threading.Thread(target=run, daemon=True)
    th.start()
    return srv, th


def _local_warm(home, body, op="call"):
    """Run the real warm remote script on this machine, as if HOME were the clef machine's."""
    cmd = clef_client._warm_command(op, 5, py=sys.executable)
    r = subprocess.run(["sh", "-c", _unwrap(cmd)], input=body, capture_output=True, env={**os.environ, "HOME": home}, timeout=30)
    return r.stdout.decode(), r.stderr.decode(), r.returncode


def _unwrap(cmd):
    import shlex
    return shlex.split(cmd)[2]


def _leftovers(home):
    return [n for n in os.listdir(home) if n.startswith(".clefcall.") and n != ".clefcall.lock"]


# ---- idle-exit logic and the single-instance lock ----

def test_idle_expired_logic():
    assert not clefd.idle_expired(100, 699.9, 600)
    assert clefd.idle_expired(100, 700, 600)


def test_single_instance_lock(home):
    lock = clefd.paths(home)[2]
    first = clefd.acquire_single_instance(lock)
    assert first is not None
    assert clefd.acquire_single_instance(lock) is None  # a second daemon cannot start
    os.close(first)
    again = clefd.acquire_single_instance(lock)  # released with the first holder
    assert again is not None
    os.close(again)


def test_serve_exits_on_idle_with_fake_clock(home):
    now = [0.0]
    srv = clefd.bind(clefd.paths(home)[1])
    srv.settimeout(0.01)

    def clock():
        now[0] += 100  # every look at the clock is 100 s later: idle 300 s expires on the 4th look
        return now[0]
    clefd.serve(srv, lambda r: REPLY, home, 300, clock=clock)  # returns instead of hanging
    srv.close()


def test_serve_exits_on_stop_request(home):
    srv, th = _fake_daemon(home, lambda r: dict(REPLY))
    out, _, code = _local_warm(home, b"{}", op="stop")
    assert "STOPPING" in out
    th.join(5)
    assert not th.is_alive()
    srv.close()


# ---- cleanup contract ----

def test_warm_call_leaves_nothing_and_daemon_sees_payload(home):
    seen = []

    def judge(req):
        seen.append((req, _leftovers(home)))  # the payload dir exists while the call runs
        return dict(REPLY)
    srv, th = _fake_daemon(home, judge)
    out, err, code = _local_warm(home, json.dumps({"state": "s", "questions": Q}).encode())
    assert code == 0 and out.startswith(clefd.MARK), (out, err)
    assert seen and seen[0][0]["state"] == "s" and len(seen[0][1]) == 1
    assert _leftovers(home) == []
    assert not os.path.exists(os.path.join(home, ".clefcall.lock"))  # per-call lock released too
    _local_warm(home, b"{}", op="stop")
    th.join(5)
    srv.close()


def test_no_daemon_exits_78_and_leaves_nothing(home):
    out, err, code = _local_warm(home, b"{}")
    assert code == clef_client.NO_DAEMON
    assert _leftovers(home) == []


def test_daemon_refuses_paths_outside_its_payload_dirs(home):
    assert clefd.payload_ok(home, os.path.join(home, ".clefcall.abc123", "req.json"))
    for bad in ("/etc/passwd", os.path.join(home, "secret.json"), os.path.join(home, ".clefcall.lock", "req.json"),
                os.path.join(home, ".clefcall.abc123", "..", "x", "req.json"),
                os.path.join(home, ".clefcall.abc123", "other.json")):
        assert not clefd.payload_ok(home, bad), bad
    reply, stop = clefd.handle(json.dumps({"req": "/etc/passwd"}), lambda r: REPLY, home)
    assert reply.startswith(clefd.ERR) and not stop


def test_a_failing_judge_call_does_not_kill_the_daemon(home):
    d = os.path.join(home, ".clefcall.zzz111")
    os.makedirs(d)
    open(os.path.join(d, "req.json"), "w").write("{}")

    def boom(req):
        raise RuntimeError("model blew up")
    reply, stop = clefd.handle(json.dumps({"req": os.path.join(d, "req.json")}), boom, home)
    assert reply.startswith(clefd.ERR) and "RuntimeError" in reply and not stop


# ---- client: warm use, first-need start, fallback ----

@pytest.fixture
def warm(monkeypatch):
    monkeypatch.setattr(clef_client, "PROFILE", CLEF)
    monkeypatch.setattr(clef_client, "WARM", True)
    calls = []
    line = f"{clef_client.MARK}{json.dumps({**REPLY, '_secs': {'load': 0, 'judge': 1.0}})}\n"
    state = {"daemon": False, "start_ok": True}

    def warm_t(body, timeout):
        calls.append("warm")
        return (line, "", 0) if state["daemon"] else ("", "", clef_client.NO_DAEMON)

    def start_t():
        calls.append("start")
        if state["start_ok"]:
            state["daemon"] = True
            return "CLEFD:READY\n", "", 0
        return "CLEFD:ERR boom\n", "", 1

    def stop_t():
        calls.append("stop")
        state["daemon"] = False
        return "", "", 0

    def one_shot(body, timeout):
        calls.append("oneshot")
        return f"{clef_client.MARK}{json.dumps(REPLY)}\n", "", 0

    monkeypatch.setattr(clef_client, "warm_transport", warm_t)
    monkeypatch.setattr(clef_client, "start_transport", start_t)
    monkeypatch.setattr(clef_client, "stop_transport", stop_t)
    monkeypatch.setattr(clef_client, "transport", one_shot)
    state["calls"] = calls
    return state


def test_first_need_starts_the_daemon_then_reuses_it(warm):
    r1 = clef_client.ask("state text", Q)
    r2 = clef_client.ask("state text", Q)
    assert warm["calls"] == ["warm", "start", "warm", "warm"]
    assert r1["warm"] and r2["warm"] and r2["answers"]["pick"]["choice"] == "a"


def test_falls_back_to_one_shot_when_the_daemon_cannot_start(warm):
    warm["start_ok"] = False
    r = clef_client.ask("state text", Q)
    assert warm["calls"] == ["warm", "start", "stop", "oneshot"]
    assert not r["warm"] and r["answers"]["pick"]["choice"] == "a"


def test_falls_back_and_stops_daemon_when_a_warm_call_errors(warm, monkeypatch):
    monkeypatch.setattr(clef_client, "warm_transport", lambda b, t: ("CLEFERR:oops\n", "", 0))
    r = clef_client.ask("state text", Q)
    assert not r["warm"] and r["answers"]["pick"]["choice"] == "a"


def test_warm_timeout_falls_back(warm, monkeypatch):
    def slow(b, t):
        raise subprocess.TimeoutExpired("ssh", t)
    monkeypatch.setattr(clef_client, "warm_transport", slow)
    r = clef_client.ask("state text", Q)
    assert not r["warm"]


def test_warm_off_never_touches_the_daemon(warm, monkeypatch):
    monkeypatch.setattr(clef_client, "WARM", False)
    clef_client.ask("state text", Q)
    assert warm["calls"] == ["oneshot"]


def test_secret_is_blocked_before_any_transport(warm):
    with pytest.raises(clef_client.SecretBlocked):
        clef_client.ask("password: hunter2 AKIAIOSFODNN7EXAMPLE sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789", Q)
    assert warm["calls"] == []


# ---- live (the clef machine) ----

@pytest.mark.live
@pytest.mark.skipif(os.environ.get("SUPERJEV_TEST_LIVE") != "1", reason="live: set SUPERJEV_TEST_LIVE=1 (needs the clef machine)")
def test_live_cold_then_warm_then_idle_exit_and_clean_tmp(monkeypatch):
    monkeypatch.setattr(clef_client, "WARM", True)
    monkeypatch.setattr(clef_client, "IDLE_SECS", 20)
    monkeypatch.setattr(clef_client, "PROFILE", CLEF)
    ssh = lambda cmd: subprocess.run(clef_client._ssh_cmd(cmd), capture_output=True, text=True, timeout=60).stdout
    clef_client.stop_transport()
    state, q = "Invoice 4471 from Acme was paid on March 3.", {"pick": {"type": "choice", "instructions": "Which document is relevant to: who was paid on March 3?",
                                                                        "criteria": {"a": "Acme invoice paid March 3", "b": "gym membership terms"}}}
    r1 = clef_client.ask(state, q)
    r2 = clef_client.ask(state, q)
    assert r1["warm"] and r2["warm"] and r2["answers"]["pick"]["choice"] == "a"
    assert r2["latency_ms"] < r1["latency_ms"]
    assert ssh("ls -d ~/.clefcall.* 2>/dev/null | grep -v lock | wc -l").strip() == "0"
    time.sleep(40)  # idle 20 s: the daemon exits and frees the model
    assert ssh("ps -axo command | grep '[c]lef-test/.venv/bin/python\\|[p]ython - --idle' | wc -l").strip() == "0"
    assert ssh("ls ~/.clefd/sock 2>/dev/null | wc -l").strip() == "0"
