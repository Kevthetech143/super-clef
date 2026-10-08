#!/usr/bin/env python3
"""Clean honest not-found for the clef judge: a strong "none" with nothing confirmed lists no leads; a weak
"none" keeps them with the leans-none note. Stub judge, made-up notes, no network, no clef machine.

    python3 -m pytest skills/super-jev/tests/test_clef_notfound.py -q

The bar (judge_profiles.json clef none_bar = 0.9) was chosen on the 30-question dev set: the five absent
questions got a none at 0.937-0.965, the only none on an answerable question got 0.57 (replay of the saved pools).
"""
import dataclasses
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import judge_profile  # noqa: E402
import judges  # noqa: E402
import ask  # noqa: E402

CLEF = judge_profile.load("clef")
NOTES = {
    "a.md": "The orchid greenhouse opens at 9am. Orchid watering is on Mondays.",
    "b.md": "Greenhouse supply order: pots, bark, moss. Orchid food is blue.",
    "c.md": "Notes about the garden shed key and the greenhouse door.",
}
Q = "what is the orchid greenhouse gate code"


def _reply(choice, prob):
    others = [c for c in ("file_1", "file_2", "file_3", "none") if c != choice]
    probs = {choice: prob, **{o: round((1 - prob) / len(others), 4) for o in others}}
    return {"answers": {"pick": {"type": "choice", "choice": choice, "confidence": prob, "probabilities": probs}},
            "model": "clef-flash", "usage": {"input_tokens": 600}}


def _run(tmp_path, monkeypatch, capsys, reply, profile=CLEF):
    files = {}
    for name, text in NOTES.items():
        p = tmp_path / name
        p.write_text(text)
        files[str(p)] = text
    cache = tmp_path / "cache"  # a prepared state: the empty-cache first-run path is not under test here
    cache.mkdir()
    (cache / "p1.json").write_text("{}")
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", cache)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(judges, "profile", lambda: profile)
    ask._CLEF.update(low_trust=set(), leans_none=False, strong_none=False)
    ask._STAGE.clear()
    monkeypatch.setattr(ask, "load_cache_files", lambda ptr: {})
    monkeypatch.setattr(ask, "word_search", lambda *a, **k: [])
    monkeypatch.setattr(ask, "candidate_files", lambda *a, **k: [
        ("p1", p, {"sha256": ask.sha256_file(Path(p))}) for p in files])
    monkeypatch.setattr(ask.zoom, "run", lambda *a, **k: (list(files), [], {}))
    monkeypatch.setattr(ask, "memory", lambda r: {"status": "miss"} if r["action"] == "cached" else
                        {"pointers": ["p1"]} if r["action"] == "panel" else {"status": "candidates", "candidates": []})
    monkeypatch.setattr(judges, "ask", lambda s, q, timeout=0: reply)
    sdir = tmp_path / "state"
    sdir.mkdir()
    ask.lookup(Q, "me", sdir)
    out = capsys.readouterr().out
    top = []
    for line in reversed((sdir / "lookups.jsonl").read_text().splitlines()):
        rec = json.loads(line)
        if rec.get("kind") == "lookup" and rec.get("question") == Q:
            top = [t["path"] for t in rec.get("top", [])]
            break
    return top, out


def test_the_profile_carries_the_bar_and_jev_has_none():
    assert CLEF.none_bar == 0.9
    assert judge_profile.load("typesafe-jev").none_bar == 0.0


def test_a_strong_none_with_nothing_confirmed_is_a_clean_not_found(tmp_path, monkeypatch, capsys):
    top, out = _run(tmp_path, monkeypatch, capsys, _reply("none", 0.96))
    assert top == [], "no leads listed"
    assert out.startswith("OUTCOME: no") and "leans none" not in out
    assert not any(line.lstrip().startswith(("confirmed", "possible", "unchecked")) for line in out.splitlines())
    assert ask._CLEF["strong_none"] is True


def test_a_weak_none_keeps_the_leads_and_the_leans_none_note(tmp_path, monkeypatch, capsys):
    top, out = _run(tmp_path, monkeypatch, capsys, _reply("none", 0.57))
    assert len(top) == 3
    assert "leans none of these" in out
    assert ask._CLEF["strong_none"] is False


def test_a_bar_just_under_the_line_does_not_clear(tmp_path, monkeypatch, capsys):
    top, _ = _run(tmp_path, monkeypatch, capsys, _reply("none", 0.89))
    assert len(top) == 3


def test_a_confirmed_pick_is_never_dropped(tmp_path, monkeypatch, capsys):
    top, _ = _run(tmp_path, monkeypatch, capsys, _reply("file_1", 0.95))
    assert top, "an answerable question keeps its file"
    assert ask._CLEF["strong_none"] is False


def test_with_the_bar_off_a_strong_none_still_keeps_the_leads(tmp_path, monkeypatch, capsys):
    top, out = _run(tmp_path, monkeypatch, capsys, _reply("none", 0.99), profile=dataclasses.replace(CLEF, none_bar=0.0))
    assert len(top) == 3 and "leans none of these" in out


def test_a_failed_call_is_never_a_not_found(tmp_path, monkeypatch, capsys):
    top, _ = _run(tmp_path, monkeypatch, capsys, {"answers": {}})  # no pick in the reply
    assert ask._CLEF["strong_none"] is False
