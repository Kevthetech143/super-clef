#!/usr/bin/env python3
"""Per-file verdicts in the one clef call: each file in the package also gets a yes/no ("does it state the
answer"). The verdicts gate, the pick ranks: files at or above file_yes_bar are kept, by pick probability; the
rest are listed after them. A "none" whose best file yes is under none_file_bar is a clean not-found.
Stub judge, made-up notes, no network, no clef machine.

    python3 -m pytest skills/super-jev/tests/test_clef_file_verdicts.py -q
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
NOTES = {
    "a.md": "Orchid greenhouse gate: orchid greenhouse hours, orchid greenhouse map.",
    "b.md": "Greenhouse gate notes. Orchid pots.",
    "c.md": "The orchid greenhouse gate code is 4471.",
}
Q = "what is the orchid greenhouse gate code"


def _reply(choice, probs, yes):
    """A clef reply; given dicts by note name, it is built from the package the call was sent."""
    if isinstance(probs, dict) and set(probs) - {"none"} <= set(NOTES) and not str(choice).startswith("file_"):
        return lambda names: _reply(choice if choice == "none" else next(k for k, n in names.items() if n == choice),
                                    {**{k: probs[n] for k, n in names.items()}, "none": probs.get("none", 0.0)},
                                    [yes[names[k]] for k in sorted(names)] if isinstance(yes, dict) else yes)
    answers = {"pick": {"type": "choice", "choice": choice, "confidence": probs[choice], "probabilities": probs}}
    answers.update({f"ok_file_{i + 1}": {"type": "noul", "noul": v} for i, v in enumerate(yes)})
    return {"answers": answers, "model": "clef-flash", "usage": {"input_tokens": 900}}


def _run(tmp_path, monkeypatch, capsys, reply):
    files = {}
    for name, text in NOTES.items():
        p = tmp_path / name
        p.write_text(text)
        files[str(p)] = text
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "p1.json").write_text("{}")
    sent = {}
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", cache)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(ask, "CLEF_VERDICTS", True)
    monkeypatch.setattr(judges, "profile", lambda: CLEF)
    monkeypatch.setattr(ask, "load_cache_files", lambda ptr: {})
    monkeypatch.setattr(ask, "word_search", lambda *a, **k: [])
    monkeypatch.setattr(ask, "candidate_files", lambda *a, **k: [
        ("p1", p, {"sha256": ask.sha256_file(Path(p))}) for p in files])
    monkeypatch.setattr(ask.toc_search, "run", lambda *a, **k: (list(files), [], {}))
    monkeypatch.setattr(ask, "memory", lambda r: {"status": "miss"} if r["action"] == "cached" else
                        {"pointers": ["p1"]} if r["action"] == "panel" else {"status": "candidates", "candidates": []})

    def judge(state, qs, timeout=0):
        sent.update(state=state, qs=qs)
        return reply({k: v["name"] for k, v in state.items()}) if callable(reply) else reply
    monkeypatch.setattr(judges, "ask", judge)
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
    names = {k: v["name"] for k, v in sent["state"].items()}
    return top, out, names, sent["qs"]


def test_the_profile_carries_both_bars():
    assert (CLEF.file_yes_bar, CLEF.none_file_bar) == (0.5, 0.2)
    jev = judge_profile.load("typesafe-jev")
    assert (jev.file_yes_bar, jev.none_file_bar) == (0.0, 0.0)


def test_one_call_carries_a_verdict_per_file(tmp_path, monkeypatch, capsys):
    reply = _reply("none", {"file_1": 0.1, "file_2": 0.1, "file_3": 0.1, "none": 0.7}, [0.9, 0.9, 0.9])
    _, _, names, qs = _run(tmp_path, monkeypatch, capsys, reply)
    assert set(qs) == {"pick", "ok_file_1", "ok_file_2", "ok_file_3"}
    assert all(qs[f"ok_{k}"]["type"] == "noul" for k in names)


def test_all_no_and_a_none_under_the_bar_is_a_clean_not_found(tmp_path, monkeypatch, capsys):
    reply = _reply("none", {"file_1": 0.1, "file_2": 0.1, "file_3": 0.1, "none": 0.7}, [0.05, 0.1, 0.02])
    top, out, _, _ = _run(tmp_path, monkeypatch, capsys, reply)
    assert top == [], "no leads listed"
    assert out.startswith("OUTCOME: no") and "leans none" not in out
    assert ask._CLEF["strong_none"] is True


def test_a_none_with_one_file_near_yes_keeps_the_leads(tmp_path, monkeypatch, capsys):
    reply = _reply("none", {"file_1": 0.1, "file_2": 0.1, "file_3": 0.1, "none": 0.7}, [0.05, 0.3, 0.02])
    top, out, _, _ = _run(tmp_path, monkeypatch, capsys, reply)
    assert len(top) == 3 and "leans none of these" in out
    assert ask._CLEF["strong_none"] is False


def test_a_wrong_pick_with_a_yes_on_the_gold_puts_the_gold_first(tmp_path, monkeypatch, capsys):
    reply = _reply("a.md", {"a.md": 0.6, "b.md": 0.1, "c.md": 0.2, "none": 0.1}, {"a.md": 0.1, "b.md": 0.2, "c.md": 0.95})
    top, _, names, _ = _run(tmp_path, monkeypatch, capsys, reply)
    read_order = [names[k] for k in sorted(names)]
    assert top[0] == "c.md", "the gold file, with the only yes, is ranked first"
    assert top[1:] == [n for n in read_order if n != "c.md"], "the demoted files stay listed, in the read list's order"


def test_all_files_yes_are_ordered_by_pick_probability(tmp_path, monkeypatch, capsys):
    reply = _reply("b.md", {"a.md": 0.2, "b.md": 0.5, "c.md": 0.25, "none": 0.05}, {"a.md": 0.9, "b.md": 0.8, "c.md": 0.7})
    top, _, _, _ = _run(tmp_path, monkeypatch, capsys, reply)
    assert top == ["b.md", "c.md", "a.md"]


def test_a_reply_without_verdicts_reads_as_the_pick_alone(tmp_path, monkeypatch, capsys):
    reply = _reply("c.md", {"a.md": 0.02, "b.md": 0.02, "c.md": 0.95, "none": 0.01}, [])
    top, _, _, _ = _run(tmp_path, monkeypatch, capsys, reply)
    assert top[0] == "c.md" and len(top) == 3
