#!/usr/bin/env python3
"""Super Clef's judge: the clef profile, the ssh client (with a stub in place of the clef machine), the short-package
confirm step in ask.py. No network, no clef machine, no key: every judge reply here is a stub.

    python3 -m pytest skills/super-jev/tests/test_clef_judge.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import judge_profile  # noqa: E402
import judges  # noqa: E402
import clef_client  # noqa: E402
import ask  # noqa: E402

CLEF = judge_profile.load("clef")


@pytest.fixture
def clef(monkeypatch):
    """The clef profile in force inside the client and in ask.py's confirm step."""
    monkeypatch.setattr(clef_client, "PROFILE", CLEF)
    monkeypatch.setattr(ask, "CLEF", True)
    ask._CLEF.update(low_trust=set(), leans_none=False)
    ask._STAGE.clear()
    return CLEF


def _reply(choice, prob, others=()):
    probs = {choice: prob, **{o: round((1 - prob) / max(len(others), 1), 4) for o in others}}
    return {"answers": {"pick": {"type": "choice", "choice": choice, "confidence": prob, "probabilities": probs}},
            "model": "clef-flash", "usage": {"input_tokens": 600}, "_secs": {"load": 2.7, "judge": 6.1}}


def _transport(reply=None, out=None, err="", code=0, seen=None):
    def go(body, timeout):
        if seen is not None:
            seen.append(json.loads(body))
        text = out if out is not None else f"load noise\n{clef_client.MARK}{json.dumps(reply)}\n"
        return text, err, code
    return go


QS = {"pick": {"type": "choice", "instructions": "Question: x\nWhich file states the answer? When torn, pick none.",
               "criteria": {"file_1": "a.md answers the question", "none": "none of the files states the answer"}}}
STATE = {"file_1": {"name": "a.md", "text": "The ENT clinic phone number is 212-555-0100."}}


# ----------------------------------------------------------------------------------------- profile
def test_the_clef_profile_is_keyless_free_and_small_window():
    p = CLEF
    assert (p.kind, p.name, p.model) == ("clef", "clef", "clef-flash")
    assert p.key_required is False and p.key_env == "" and p.input_usd_per_mtok == 0
    assert p.window_tokens <= 2048  # prefill is ~96 tokens/s: one call is a short package
    assert "clef" in judge_profile.judge_names() and "clef-flash" in judge_profile.judge_names()


def test_the_table_default_is_clef_and_fake_keeps_the_jev_numbers():
    default, profiles = judge_profile._read(judge_profile.PROFILES_PATH)
    assert default == "clef"
    fake = judge_profile.load("fake")
    assert fake.name == "typesafe-jev" and fake.window_tokens == 32768


def test_no_key_is_needed_to_call_the_clef_judge(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(judges, "profile", lambda: CLEF)
    assert judges.key_present() and judges.require_key() == ""


def test_the_door_knows_the_clef_implementation():
    assert judges.IMPLEMENTATIONS["clef"] == "clef_client"


# ----------------------------------------------------------------------------------------- client
def test_a_clef_call_returns_the_jev_reply_shape(clef):
    seen = []
    clef_client.transport = _transport(_reply("file_1", 0.93, ["none"]), seen=seen)
    got = clef_client.ask(STATE, QS)
    assert got["answers"]["pick"]["choice"] == "file_1"
    assert got["answers"]["pick"]["probabilities"]["file_1"] == 0.93
    assert got["model"] == "clef-flash" and got["input_tokens"] == 600 and got["secs"]["judge"] == 6.1
    assert seen[0]["state"] == STATE and seen[0]["model"] == "clef-flash"  # the Jev-shaped request, unchanged


@pytest.fixture(autouse=True)
def _restore_transport():
    real = clef_client.transport
    yield
    clef_client.transport = real


def test_a_package_over_the_short_call_budget_is_refused_never_truncated(clef):
    big = {"file_1": {"name": "a.md", "text": "word " * 4000}}
    clef_client.transport = _transport(_reply("file_1", 0.9))
    with pytest.raises(judges.TooBig):
        clef_client.ask(big, QS)


def test_a_secret_is_never_sent(clef):
    called = []
    clef_client.transport = lambda body, timeout: called.append(body) or ("", "", 0)
    with pytest.raises(judges.SecretBlocked):
        clef_client.ask({"file_1": {"name": "a.md", "text": "key AKIAIOSFODNN7EXAMPLE and sk-ant-api03-" + "a" * 40}}, QS)
    assert called == []


def test_failures_are_typed_and_never_a_verdict(clef):
    clef_client.transport = _transport(out="", err="ssh: connect to host: Connection timed out", code=255)
    with pytest.raises(judges.Unreachable):
        clef_client.ask(STATE, QS)
    clef_client.transport = _transport(out="no marker here\n", err="Traceback", code=1)
    with pytest.raises(judges.BadReply):
        clef_client.ask(STATE, QS)
    clef_client.transport = _transport(out=f"{clef_client.MARK}not json\n")
    with pytest.raises(judges.BadReply):
        clef_client.ask(STATE, QS)
    clef_client.transport = _transport(out=f"{clef_client.MARK}{json.dumps({'no': 'answers'})}\n")
    with pytest.raises(judges.BadReply):
        clef_client.ask(STATE, QS)

    def slow(body, timeout):
        raise subprocess.TimeoutExpired("ssh", timeout)
    clef_client.transport = slow
    with pytest.raises(judges.Unreachable):
        clef_client.ask(STATE, QS)


def test_the_remote_script_deletes_the_payload_and_the_lock_after_every_call(tmp_path):
    """Runs the exact remote script locally with a fake clef python: the payload reaches it on stdin, a temp
    dir exists during the call, and after the call (success or failure) neither the dir nor the lock is left."""
    home = tmp_path / "home"
    (home / "clef-test" / ".venv" / "bin").mkdir(parents=True)
    fake = home / "clef-test" / ".venv" / "bin" / "python"
    fake.write_text('#!/bin/sh\n# args: -c CODE req.json\nshift; shift\nf="$1"\nwhile ! [ -f "$f" ]; do :; done\n'
                    'echo "SAW:$(cat "$f")" > "$HOME/saw.txt"\nls -d "$HOME"/.clefcall.* > "$HOME/during.txt"\n'
                    'ls -d "$HOME"/.clefcall.lock > "$HOME/lock-during.txt"\n'
                    'if [ -f "$HOME/fail" ]; then echo boom >&2; exit 3; fi\necho "CLEFJSON:{}"\n')
    fake.chmod(0o755)
    script = clef_client._SH % {"wait": 3, "dir": str(home / "clef-test"), "py": "x"}
    env = {**os.environ, "HOME": str(home)}
    r = subprocess.run(["sh", "-c", script], input=b'{"state":"payload-xyz"}', capture_output=True, env=env, timeout=30)
    assert r.returncode == 0 and b"CLEFJSON:{}" in r.stdout
    assert "payload-xyz" in (home / "saw.txt").read_text()
    assert (home / "during.txt").read_text().strip()  # the temp dir existed during the call
    assert (home / "lock-during.txt").read_text().strip()  # and the lock
    assert not list(home.glob(".clefcall.*")), "payload dir or lock left on the clef machine"
    (home / "fail").write_text("1")
    r = subprocess.run(["sh", "-c", script], input=b'{"state":"payload-xyz"}', capture_output=True, env=env, timeout=30)
    assert r.returncode == 3
    assert not list(home.glob(".clefcall.*")), "a failed call must leave nothing either"


def test_only_one_clef_process_at_a_time_a_busy_lock_waits_then_gives_up(tmp_path):
    home = tmp_path / "home"
    (home / "clef-test" / ".venv" / "bin").mkdir(parents=True)
    (home / ".clefcall.lock").mkdir()
    holder = subprocess.Popen(["sleep", "30"])
    try:
        (home / ".clefcall.lock" / "pid").write_text(str(holder.pid))
        script = clef_client._SH % {"wait": 2, "dir": str(home / "clef-test"), "py": "x"}
        r = subprocess.run(["sh", "-c", script], input=b"{}", capture_output=True,
                           env={**os.environ, "HOME": str(home)}, timeout=30)
        assert r.returncode == 75 and b"clef busy" in r.stderr
        assert (home / ".clefcall.lock").is_dir(), "a lock held by a live process is never taken over"
        assert not [p for p in home.glob(".clefcall.*") if p.name != ".clefcall.lock"]
    finally:
        holder.kill()
        holder.wait()  # reaped, so its pid is really gone
    # a lock whose owner is gone is stale: the next call takes it
    fake = home / "clef-test" / ".venv" / "bin" / "python"
    fake.write_text('#!/bin/sh\necho "CLEFJSON:{}"\n')
    fake.chmod(0o755)
    script = clef_client._SH % {"wait": 2, "dir": str(home / "clef-test"), "py": "x"}
    r = subprocess.run(["sh", "-c", script], input=b"{}", capture_output=True,
                       env={**os.environ, "HOME": str(home)}, timeout=30)
    assert r.returncode == 0 and not list(home.glob(".clefcall.*"))


# ----------------------------------------------------------------------------------------- ask.py
def _files(tmp_path, n=3):
    out = []
    for i in range(n):
        f = tmp_path / f"note{i}.md"
        f.write_text(f"# Note {i}\n" + "filler line about nothing\n" * 40 + f"The ENT clinic phone number is 212-555-01{i:02d}.\n"
                     + "more filler\n" * 40)
        out.append(str(f))
    return out


def test_the_passage_is_a_short_window_around_the_question_words(tmp_path):
    f = _files(tmp_path, 1)[0]
    got = ask.clef_passage("ENT clinic phone number", f)
    assert len(got) <= ask.CLEF_PASSAGE_CHARS and "212-555-0100" in got
    assert ask.clef_passage("anything", str(tmp_path / "missing.md")) is None


def test_a_secret_file_is_held_and_never_in_the_package(clef, tmp_path, monkeypatch):
    ok = _files(tmp_path, 2)
    bad = tmp_path / "keys.md"
    bad.write_text("ENT clinic phone number\naws AKIAIOSFODNN7EXAMPLE secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n")
    sent = []
    monkeypatch.setattr(judges, "ask", lambda s, q, timeout=0: sent.append(s) or _reply("file_1", 0.8, ["file_2", "none"]))
    scores, partial, err, notes = ask.clef_confirm("ENT clinic phone number", ok + [str(bad)])
    assert err is None
    assert "AKIA" not in json.dumps(sent) and "keys.md" not in json.dumps(sent)
    assert notes[str(bad)] == ask.HELD_SECRET


def test_a_clean_pick_scores_its_probability_and_the_rest_stay_unconfirmed(clef, tmp_path, monkeypatch):
    fs = _files(tmp_path, 3)
    sent = []
    monkeypatch.setattr(judges, "ask", lambda s, q, timeout=0: sent.append((s, q)) or _reply("file_2", 0.92, ["file_1", "file_3", "none"]))
    scores, partial, err, notes = ask.clef_confirm("ENT clinic phone number", fs)
    state, qs = sent[0]
    picked = fs[int(state["file_2"]["name"][4]) ]
    assert scores == {picked: 0.92} and err is None
    assert picked not in notes and all(notes[p] == ask.INCONCLUSIVE for p in fs if p != picked)
    assert ask._CLEF["low_trust"] == set() and ask._CLEF["leans_none"] is False
    assert all(len(v["text"]) <= ask.CLEF_PASSAGE_CHARS for v in state.values()) and len(state) <= ask.CLEF_PACKAGE_FILES
    assert not any("path" in v for v in state.values())  # names only: no path leaves the Mac
    assert set(qs["pick"]["criteria"]) == {"file_1", "file_2", "file_3", "none"}


def test_a_pick_under_the_trust_min_is_low_trust(clef, tmp_path, monkeypatch):
    fs = _files(tmp_path, 2)
    monkeypatch.setattr(judges, "ask", lambda s, q, timeout=0: _reply("file_1", 0.8, ["file_2", "none"]))
    scores, _, _, notes = ask.clef_confirm("ENT clinic phone number", fs)
    (p,) = scores
    assert p in ask._CLEF["low_trust"], "a pick under 0.9 is reported as possible, not certain"


def test_none_is_low_trust_every_file_kept_with_the_leans_none_flag(clef, tmp_path, monkeypatch):
    fs = _files(tmp_path, 3)
    monkeypatch.setattr(judges, "ask", lambda s, q, timeout=0: _reply("none", 0.97, ["file_1", "file_2", "file_3"]))
    scores, _, err, notes = ask.clef_confirm("ENT clinic phone number", fs)
    assert scores == {} and err is None
    assert ask._CLEF["leans_none"] is True and all(notes[p] == ask.INCONCLUSIVE for p in fs)


def test_a_failed_call_is_no_verdict_all_files_unchecked(clef, tmp_path, monkeypatch):
    fs = _files(tmp_path, 2)

    def boom(s, q, timeout=0):
        raise judges.Unreachable("could not reach clef on the clef machine")
    monkeypatch.setattr(judges, "ask", boom)
    scores, _, err, notes = ask.clef_confirm("ENT clinic phone number", fs)
    assert scores == {} and "no verdict" in err and all(notes[p] == ask.INCONCLUSIVE for p in fs)
    assert ask._CLEF["leans_none"] is False  # a failure is not a "none"


def test_a_claim_is_not_judged_in_the_confirm_step(clef, tmp_path, monkeypatch):
    fs = _files(tmp_path, 2)
    monkeypatch.setattr(ask, "_CLAIM", {"text": "the ENT phone is 212-555-0100", "word": None})
    monkeypatch.setattr(judges, "ask", lambda *a, **k: pytest.fail("no judge call in the claim confirm step"))
    scores, _, err, notes = ask.clef_confirm("the ENT phone is 212-555-0100", fs)
    assert scores == {} and err is None and notes == {}
