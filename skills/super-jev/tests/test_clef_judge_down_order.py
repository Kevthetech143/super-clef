#!/usr/bin/env python3
"""Clef judge down: the final list keeps the word-search order and the reply names the judge as down.
Stub judge that raises, made-up notes, no network, no clef machine.

    python3 -m pytest skills/super-jev/tests/test_clef_judge_down_order.py -q
"""
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import judge_profile  # noqa: E402
import judges  # noqa: E402
import ask  # noqa: E402

CLEF = judge_profile.load("clef")
# word-search order differs from both name order and reverse name order
NOTES = {
    "a.md": "The orchid greenhouse opens at 9am.",
    "b.md": "Greenhouse supply order: pots, bark, moss.",
    "z.md": "The orchid greenhouse gate code is 4471.",
}
RANK = ["a.md", "z.md", "b.md"]
Q = "what is the orchid greenhouse gate code"


def _run(tmp_path, monkeypatch, capsys):
    files = {}
    for name, text in NOTES.items():
        p = tmp_path / name
        p.write_text(text)
        files[name] = str(p)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "p1.json").write_text("{}")
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", cache)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(judges, "profile", lambda: CLEF)
    ask._CLEF.update(low_trust=set(), leans_none=False, strong_none=False)
    ask._STAGE.clear()
    monkeypatch.setattr(ask, "load_cache_files", lambda ptr: {})
    ranked = [(10 - i, files[n], "p1") for i, n in enumerate(RANK)]
    monkeypatch.setattr(ask, "word_search", lambda *a, **k: ranked)
    monkeypatch.setattr(ask, "candidate_files", lambda *a, **k: [
        ("p1", p, {"sha256": ask.sha256_file(Path(p))}) for _s, p, _ptr in ranked])
    monkeypatch.setattr(ask.toc_search, "run", lambda *a, **k: ([p for _s, p, _ptr in ranked], [], {}))
    monkeypatch.setattr(ask, "memory", lambda r: {"status": "miss"} if r["action"] == "cached" else
                        {"pointers": ["p1"]} if r["action"] == "panel" else {"status": "candidates", "candidates": []})

    def down(s, q, timeout=0):
        raise judges.JudgeError("clef machine unreachable")
    monkeypatch.setattr(judges, "ask", down)
    sdir = tmp_path / "state"
    sdir.mkdir()
    ask.lookup(Q, "me", sdir)
    out = capsys.readouterr().out
    top = []
    for line in reversed((sdir / "lookups.jsonl").read_text().splitlines()):
        rec = json.loads(line)
        if rec.get("kind") == "lookup" and rec.get("question") == Q:
            top = [Path(t["path"]).name for t in rec.get("top", [])]
            break
    return top, out


def test_a_dead_judge_keeps_the_word_search_order(tmp_path, monkeypatch, capsys):
    top, out = _run(tmp_path, monkeypatch, capsys)
    assert top == RANK


def test_a_dead_judge_is_named_plainly(tmp_path, monkeypatch, capsys):
    _top, out = _run(tmp_path, monkeypatch, capsys)
    assert "judge" in out.lower() and "clef machine unreachable" in out
    assert not out.startswith("OUTCOME: no"), out
    print(out)
