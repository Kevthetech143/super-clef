#!/usr/bin/env python3
"""Clef's free TOC shortlist and read order: a question word in a file's own name counts twice, so a file named
for the topic reaches the TOC slots; and the files clef did not pick keep the read order, not path order.
Stub judge, made-up files, no network, no clef machine.

    python3 -m pytest skills/super-jev/tests/test_clef_toc_pick.py -q
"""
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import judge_profile  # noqa: E402
import judges  # noqa: E402
import toc_search  # noqa: E402

pytestmark = pytest.mark.real_toc  # the real TOC search, not conftest's replay
CLEF = judge_profile.load("clef")
Q = "when does the ferry leave the dock"
# Every file shares one question word in its text; only ferry-leave-times.md has the words in its own name.
TEXTS = {
    "/n/ferry-leave-times.md": "# Timetable\nBoats sail at 7:10 and 9:40 from the dock.\n",
    "/n/a-notes.md": "# Ferry\nThe ferry was built of oak.\n# Dock\nThe dock is blue.\n# Leave\nStaff leave on Fridays.\n",
    "/n/b-notes.md": "# Ferry\nThe ferry is green.\n# Dock\nIt sits at the dock.\n# Leave\nAny weekday.\n",
    "/n/c-notes.md": "# Ferry\nMarigold.\n# Dock\nCats.\n# Leave\nForms.\n",
    "/n/d-notes.md": "# Ferry\nOars.\n# Dock\nRope.\n# Leave\nNotes.\n",
    **{f"/n/other-{k}.md": "# Garden\nTulips.\n" for k in range(4)},  # files with no question word give the words weight
}
GOLD = "/n/ferry-leave-times.md"


def _ask():
    terms = ["ferry", "leave", "dock"]
    return {"read": TEXTS.get, "has_secret": lambda t: "SECRET" in t, "query_terms": lambda q: terms,
            "term_hits": lambda ts, text: sum(w in text.lower() for w in ts), "fold": str.lower}


def test_a_question_word_in_the_file_name_lifts_it_into_the_free_slots(monkeypatch):
    def no_judge(*a, **k):
        raise AssertionError("the clef shortlist calls no judge")
    monkeypatch.setattr(toc_search.judges, "ask", no_judge)
    corpus = {p: ("ptr", {"sha256": p, "description": ""}) for p in TEXTS}
    hits = [(3.0, "/n/d-notes.md", "ptr"), (2.0, "/n/c-notes.md", "ptr"), (1.0, "/n/b-notes.md", "ptr")]
    files, _chosen, trace = toc_search.run(Q, corpus, hits, _ask(), judge_free=True)
    assert files[:3] == [p for _s, p, _ptr in hits]  # the word search's three best hits keep the first slots
    assert files[3] == GOLD and trace["pick"]["calls"] == 0


def test_the_files_clef_did_not_pick_keep_the_read_order_not_path_order(tmp_path, monkeypatch, capsys):
    import json
    import ask
    notes = {"a.md": "The orchid greenhouse opens at 9am.", "b.md": "Greenhouse supply order: pots, bark, moss.",
             "z.md": "The orchid greenhouse gate is green."}
    read = ["a.md", "b.md", "z.md"]  # path order would list z.md before a.md
    q = "what is the orchid greenhouse gate code"
    files = {}
    for name, text in notes.items():
        (tmp_path / name).write_text(text)
        files[name] = str(tmp_path / name)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "p1.json").write_text("{}")
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", cache)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(judges, "profile", lambda: CLEF)
    ask._CLEF.update(low_trust=set(), leans_none=False, strong_none=False)
    ask._STAGE.clear()
    ranked = [(10 - i, files[n], "p1") for i, n in enumerate(read)]
    monkeypatch.setattr(ask, "load_cache_files", lambda ptr: {})
    monkeypatch.setattr(ask, "word_search", lambda *a, **k: ranked)
    monkeypatch.setattr(ask, "candidate_files", lambda *a, **k: [
        ("p1", p, {"sha256": ask.sha256_file(Path(p))}) for _s, p, _ptr in ranked])
    monkeypatch.setattr(ask.toc_search, "run", lambda *a, **k: ([p for _s, p, _ptr in ranked], [], {}))
    monkeypatch.setattr(ask, "memory", lambda r: {"status": "miss"} if r["action"] == "cached" else
                        {"pointers": ["p1"]} if r["action"] == "panel" else {"status": "candidates", "candidates": []})

    def clef(state, qs, timeout=0):
        pick = next(k for k, v in state.items() if "supply" in v["text"])
        probs = {k: (0.95 if k == pick else 0.01) for k in qs["pick"]["criteria"]}
        return {"answers": {"pick": {"type": "choice", "choice": pick, "probabilities": probs}}}
    monkeypatch.setattr(judges, "ask", clef)
    sdir = tmp_path / "state"
    sdir.mkdir()
    ask.lookup(q, "me", sdir)
    capsys.readouterr()
    rec = next(json.loads(ln) for ln in reversed((sdir / "lookups.jsonl").read_text().splitlines())
               if json.loads(ln).get("kind") == "lookup")
    assert [Path(t["path"]).name for t in rec["top"]] == ["b.md", "a.md", "z.md"]
