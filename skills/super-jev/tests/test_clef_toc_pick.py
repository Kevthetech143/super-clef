#!/usr/bin/env python3
"""The clef TOC pick: with the clef judge, the TOC search asks clef to pick from a small shortlist of TOC pages
(the profile's toc_pick_pool), in calls that fit clef's short-call budget, so a file the word search misses can
still be read. Stub judge, made-up files, no network, no clef machine.

    python3 -m pytest skills/super-jev/tests/test_clef_toc_pick.py -q
"""
import dataclasses
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
# The answer lives in harbor-crossings.md, which shares no word with the question. The decoys all share some.
TEXTS = {
    "/n/harbor-crossings.md": "# Harbor crossing timetable\nBoats sail at 7:10 and 9:40 from pier 3.\n# Fares\nSix coins.\n",
    "/n/dock-paint.md": "# Dock paint\nThe dock was painted blue.\n# Leave policy\nStaff leave on Fridays.\n",
    "/n/ferry-history.md": "# Ferry history\nThe first ferry was built of oak.\n# Names\nMarigold.\n",
    "/n/leave-forms.md": "# Leave forms\nFill in the leave form.\n# When\nAny weekday.\n",
    "/n/dock-cats.md": "# Dock cats\nThree cats live on the dock.\n# Food\nFish.\n",
    "/n/ferry-paint.md": "# Ferry paint\nThe ferry is green.\n# Dock\nIt sits at the dock.\n",
    "/n/lighthouse.md": "# Lighthouse\nThe lamp turns.\n# Keeper\nOrin.\n",
    "/n/garden.md": "# Garden\nTulips.\n# Shed\nRakes.\n",
}
GOLD = "/n/harbor-crossings.md"


def _ask():
    terms = ["ferry", "leave", "dock"]
    return {"read": TEXTS.get, "has_secret": lambda t: "SECRET" in t, "query_terms": lambda q: terms,
            "term_hits": lambda ts, text: sum(w in text.lower() for w in ts), "fold": str.lower}


def _judge(likes, none=0.02):
    """A stub clef: a page containing `likes` gets 0.9, every other page 0.02, "none" gets `none`."""
    def score(state, crit):
        return {k: (none if k == "none" else 0.9 if likes and likes in str(state.get(k, "")).lower() else 0.02) for k in crit}
    return score


def _run(monkeypatch, profile, hits=(), score=None):
    corpus = {p: ("ptr", {"sha256": p, "description": ""}) for p in TEXTS}
    sent = []
    score = score or _judge("crossing")

    def clef(state, qs, timeout=90):
        assert judge_profile.judge_tokens(state) + max(judge_profile.judge_tokens(q) for q in qs.values()) <= profile.call_tokens
        sent.append(state)
        (qid, q), = qs.items()  # one listwise question per call
        probs = score(state, q["criteria"])
        return {"answers": {qid: {"type": "choice", "choice": max(probs, key=probs.get), "probabilities": probs}}}

    monkeypatch.setattr(judges, "profile", lambda: profile)
    monkeypatch.setattr(toc_search.judges, "ask", clef)
    files, _chosen, trace = toc_search.run(Q, corpus, list(hits), _ask(), judge_free=True)
    return files, trace, sent


def test_the_clef_profile_carries_the_pick_pool_and_jev_has_none():
    assert CLEF.toc_pick_pool > 0 and CLEF.toc_page_chars > 0
    assert judge_profile.load("typesafe-jev").toc_pick_pool == 0


def test_the_clef_toc_pick_calls_the_judge_and_surfaces_a_file_word_search_misses(monkeypatch):
    hits = [(3.0, "/n/ferry-paint.md", "ptr")]
    files, trace, sent = _run(monkeypatch, CLEF, hits)
    assert sent and trace["pick"]["calls"] >= 1
    assert GOLD in files[:toc_search.KEEP_FILES + 1]
    assert files[0] == "/n/ferry-paint.md"  # the word search's best hit keeps its slot
    assert trace["pick"]["top"][0][0] == GOLD


HITS3 = [(3.0, "/n/ferry-paint.md", "ptr"), (2.0, "/n/dock-paint.md", "ptr"), (1.0, "/n/leave-forms.md", "ptr")]


def test_a_none_answer_changes_no_slots(monkeypatch):
    free, _t, _s = _run(monkeypatch, dataclasses.replace(CLEF, toc_pick_pool=0), HITS3)
    files, trace, sent = _run(monkeypatch, CLEF, HITS3, _judge("crossing", none=0.95))
    assert sent and files == free
    assert trace["pick"]["picked"] is None and trace["pick"]["none"] == [0.95]


def test_the_third_word_hit_stays_in_the_top_five(monkeypatch):
    files, trace, _s = _run(monkeypatch, CLEF, HITS3)
    assert files[:3] == [p for _s, p, _ptr in HITS3]
    assert files[3] == GOLD and trace["pick"]["picked"] == GOLD


def test_a_wrong_pick_moves_a_free_file_down_one_slot_at_most(monkeypatch):
    free, _t, _s = _run(monkeypatch, dataclasses.replace(CLEF, toc_pick_pool=0), HITS3)
    files, trace, _s = _run(monkeypatch, CLEF, HITS3, _judge("garden"))
    assert trace["pick"]["picked"] == "/n/garden.md"
    for k, p in enumerate(free):
        assert p in files and files.index(p) <= k + 1


def test_a_negative_knob_is_refused_and_a_zero_page_size_turns_the_pick_off(tmp_path, monkeypatch):
    import json
    import pytest
    table = json.loads(judge_profile.PROFILES_PATH.read_text())
    table["profiles"]["clef"]["toc_pick_pool"] = -1
    bad = tmp_path / "profiles.json"
    bad.write_text(json.dumps(table))
    with pytest.raises(SystemExit):
        judge_profile.load("clef", path=bad)
    files, trace, sent = _run(monkeypatch, dataclasses.replace(CLEF, toc_page_chars=0))
    assert not sent and trace["pick"]["calls"] == 0


def test_without_a_pick_pool_the_clef_shortlist_stays_free(monkeypatch):
    files, trace, sent = _run(monkeypatch, dataclasses.replace(CLEF, toc_pick_pool=0))
    assert not sent and trace["pick"]["calls"] == 0
    assert GOLD not in files


def test_a_small_window_splits_the_pick_into_calls_that_fit(monkeypatch):
    small = dataclasses.replace(CLEF, window_tokens=CLEF.input_cap_headroom + CLEF.call_headroom + 260)
    files, trace, sent = _run(monkeypatch, small)
    assert len(sent) >= 2
    assert GOLD in files


def test_a_failed_clef_pick_keeps_the_free_shortlist(monkeypatch):
    monkeypatch.setattr(judges, "profile", lambda: CLEF)

    def down(state, qs, timeout=90):
        raise judges.Unreachable("clef machine is asleep")
    monkeypatch.setattr(toc_search.judges, "ask", down)
    corpus = {p: ("ptr", {"sha256": p, "description": ""}) for p in TEXTS}
    files, _c, trace = toc_search.run(Q, corpus, [], _ask(), judge_free=True)
    assert files and "Unreachable" in trace["pick"]["error"]


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
