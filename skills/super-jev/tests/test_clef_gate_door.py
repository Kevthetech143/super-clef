#!/usr/bin/env python3
"""Under clef the gate's door (lib/clef_client.py run as a script) returns a real verdict, and a --source save
is refused as uncalibrated, never 'gate verdict ERROR'. A stub judge stands in for the clef machine: no network.

    python3 -m pytest skills/super-jev/tests/test_clef_gate_door.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import ask  # noqa: E402
import judge_profile  # noqa: E402

STUB = '''
import sys, json
sys.path[:0] = [%r, %r]
import clef_client
VERDICT = %%r
def fake_ask(state, questions, timeout=120):
    answers = {}
    for k, q in questions.items():
        pick = VERDICT if k.startswith("c") and k[1:].isdigit() else None
        crit = list(q["criteria"])
        pick = pick if pick in crit else crit[0]
        answers[k] = {"type": "choice", "choice": pick, "confidence": 0.95,
                      "probabilities": {c: (0.95 if c == pick else 0.01) for c in crit}}
    return {"answers": answers, "model": "stub", "chunks": 1, "input_tokens": 1, "latency_ms": 1}
clef_client.ask = fake_ask
sys.exit(clef_client.main(sys.argv[1:]))
''' % (str(SKILL), str(SKILL / "lib"))


def _run(tmp_path, verdict, claim="The clinic phone number is 212-555-0100"):
    ev = tmp_path / "ev.md"
    ev.write_text("The ENT clinic phone number is 212-555-0100.\n")
    stub = tmp_path / "stub.py"
    stub.write_text(STUB % verdict)
    env = {**os.environ, "SUPERJEV_JUDGE": "clef"}
    return subprocess.run([sys.executable, str(stub), str(ev), "--kit", "reply", "--claim", claim],
                          capture_output=True, text=True, env=env, timeout=60)


def test_clef_door_runs_as_a_script_and_returns_supported(tmp_path):
    r = _run(tmp_path, "SUPPORTED")
    assert r.returncode == 0, r.stderr
    assert " c1   SUPPORTED" in r.stdout


def test_clef_door_returns_contradicted_honestly(tmp_path):
    r = _run(tmp_path, "CONTRADICTED")
    assert r.returncode == 3, r.stderr
    assert "CONTRADICTED" in r.stdout


def test_clef_door_has_an_entry_point():
    r = subprocess.run([sys.executable, str(SKILL / "lib" / "clef_client.py")], capture_output=True, text=True,
                       env={**os.environ, "SUPERJEV_JUDGE": "clef"}, timeout=60)
    assert r.returncode == 1 and "needs at least one evidence file" in r.stderr  # not silence


def test_clef_door_error_is_no_verdict(tmp_path):
    r = subprocess.run([sys.executable, str(SKILL / "lib" / "clef_client.py"), str(tmp_path / "missing.md"),
                        "--kit", "reply", "--claim", "x y z w"], capture_output=True, text=True,
                       env={**os.environ, "SUPERJEV_JUDGE": "clef"}, timeout=60)
    assert r.returncode == 1


def test_source_save_under_clef_says_uncalibrated_not_gate_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(judge_profile, "PROFILE", judge_profile.load("clef"))
    monkeypatch.setattr(ask, "run_gate", lambda *a, **k: ("ERROR", None))
    monkeypatch.setattr(ask, "memory", lambda req: {"status": "ok", "pointers": []})
    src = tmp_path / "src.txt"
    src.write_text("hello source\n")
    ask.add_manual("alice", "what does the source say", "hello", str(src), tmp_path)
    out = capsys.readouterr().out
    assert "uncalibrated" in out and "gate verdict" not in out
