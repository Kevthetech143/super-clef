#!/usr/bin/env python3
"""Person folders found by their PROFILE's Relation line, in any layout (not only the fleet's documents/<name>/).
Made-up family in a tmp dir, stub judge, no provider calls.

    python3 -m pytest skills/super-jev/tests/test_kin_word.py -q
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_index_read_path import PRINCIPAL, Rig, ask, ask_it, build, flag, sync  # noqa: E402
from file_index import FileIndex  # noqa: E402

pytestmark = pytest.mark.real_toc

FAMILY = {  # a non-fleet layout: family/<name>/, no agents/global/documents anywhere
    "family/nora/PROFILE.md": "# Nora\n- Relation: mother\n",
    "family/nora/medical/OPEN-QUESTIONS.md": "# Questions\nNora asked about the open referral. Nora's follow-up is open.\n",
    "family/gustavo/PROFILE.md": "# Gustavo\n- Relation: father\n",
    "family/gustavo/medical/OPEN-QUESTIONS.md": "# Questions\nGustavo has an open claim.\n",
    "calls/kitchen-call.md": "# Call\nmom said the pharmacy is open late on friday.\n",  # says "mom", is no one's folder
    **{f"hours/hours-{i}.md": f"# Hours {i}\nthe library is open on weekends.\n" for i in range(6)},
}
NORA = "family/nora/medical/OPEN-QUESTIONS.md"
DADS = "family/gustavo/medical/OPEN-QUESTIONS.md"
DECOY = "calls/kitchen-call.md"
ASK = "what's still open for my mom?"


def family(tmp_path, monkeypatch):
    notes, names, sdir = build(tmp_path, monkeypatch, 40)
    cdir = ask.prepare_bulk.CACHE_DIR
    cache = json.loads((cdir / "p0.json").read_text())
    for rel, text in FAMILY.items():
        f = notes / "p0" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        cache[str(f)] = {"sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "pass": True, "description": f.name, "question": ""}
    (cdir / "p0.json").write_text(json.dumps(cache))
    Rig(monkeypatch, notes, names)
    return notes / "p0", names, sdir


def found(question, sdir, capsys, monkeypatch):
    """The word search's top 5 paths in a real ask (the files that passed its coverage test)."""
    got, real = [], ask.word_search
    monkeypatch.setattr(ask, "word_search", lambda *a, **k: got.append(real(*a, **k)) or got[-1])
    ask_it(question, sdir, capsys)
    monkeypatch.setattr(ask, "word_search", real)
    return [p for _s, p, _ptr in got[-1]]


def test_person_folder_outside_global_documents(tmp_path, monkeypatch):
    root, names, _sdir = family(tmp_path, monkeypatch)
    assert ask.people(names) == {"nora": {"mother"}, "gustavo": {"father"}}
    homes = ask.person_homes(names)
    assert ask.person_of(str(root / NORA), homes) == "nora" and ask.person_of(str(root / DECOY), homes) is None


def test_my_dad_leaves_the_kin_folder_out_in_any_layout(tmp_path, monkeypatch, capsys):
    root, _names, sdir = family(tmp_path, monkeypatch)
    flag(monkeypatch, False)
    ask_it("what is still open for my dad?", sdir, capsys)
    trace = json.loads((sdir / "traces.jsonl").read_text().splitlines()[-1])["stages"]
    assert trace["person"]["who"] == ["gustavo"]
    out = found("what is still open for my dad?", sdir, capsys, monkeypatch)
    assert str(root / DADS) in out and str(root / NORA) not in out


def test_index_moves_the_person_without_a_version_bump(tmp_path, monkeypatch):
    root, _names, sdir = family(tmp_path, monkeypatch)
    sync(sdir)
    idx = FileIndex(PRINCIPAL, sdir / "index.sqlite")
    person = lambda: dict(idx.db.execute("SELECT path,person FROM fts_map"))  # noqa: E731
    assert person()[str(root / NORA)] == "nora" and person()[str(root / DECOY)] == ""
    idx.db.execute("UPDATE fts_map SET person=''")  # as an index built under the old path rule holds them
    idx.db.commit()
    idx.close()
    real = ask.person_homes  # a path-connected set lists no files in a prepare-cache: the PROFILEs come from the index
    monkeypatch.setattr(ask, "person_homes", lambda pointers, paths=None: {} if paths is None else real(pointers, paths))
    sync(sdir)
    idx = FileIndex(PRINCIPAL, sdir / "index.sqlite")
    assert person()[str(root / NORA)] == "nora" and person()[str(root / DADS)] == "gustavo"
    assert idx.fts_usable(ask.WORD_INDEX_VERSION)[0]


@pytest.mark.parametrize("fts", [False, True])
def test_kin_word_reaches_the_folder_that_never_says_it(tmp_path, monkeypatch, capsys, fts):
    root, _names, sdir = family(tmp_path, monkeypatch)
    if fts:
        sync(sdir)
    flag(monkeypatch, fts)
    for q in (ASK, "what's still open for my mom's care?", "whats open for moms care"):
        out = found(q, sdir, capsys, monkeypatch)
        assert (json.loads((sdir / "traces.jsonl").read_text().splitlines()[-1])["stages"].get("index") or {}).get(
            "fts", {}).get("used", False) is fts
        assert str(root / NORA) in out, (q, out)  # past coverage, in the top 5
        assert str(root / DECOY) in out  # a file literally saying "mom" still matches
        assert str(root / DADS) not in out


@pytest.mark.parametrize("fts", [False, True])
def test_group_word_unclaimed_kin_and_names_change_nothing(tmp_path, monkeypatch, capsys, fts):
    _root, names, sdir = family(tmp_path, monkeypatch)
    if fts:
        sync(sdir)
    flag(monkeypatch, fts)
    folks = ask.people(names)
    qs = ("what's still open for my parents?", "what's still open for my aunt?", "what's still open for nora?",
          "what is open for gustavo and nora")
    for q in qs:
        assert ask.kin_synonyms(q, ask.question_people(q, folks), folks) == ask.SYNONYMS, q
    got = [found(q, sdir, capsys, monkeypatch) for q in qs]
    monkeypatch.setattr(ask, "kin_synonyms", lambda *a: ask.SYNONYMS)  # the word search without the kin variant
    assert got == [found(q, sdir, capsys, monkeypatch) for q in qs]


def test_possessive_kin_word_resolves_the_folder():
    folks = {"nora": {"mother"}, "gustavo": {"father"}, "marvin": {"self"}}
    for q in ("whats open for moms care", "what's open for my mom's care", "my dads meds"):
        assert ask.question_people(q, folks) == ({"gustavo"} if "dad" in q else {"nora"}), q
    assert ask.question_people("what did my aunts say", folks) == set()  # no folder claims it: nothing filtered


def test_kin_word_makes_no_provider_call(tmp_path, monkeypatch, capsys):
    root, _names, sdir = family(tmp_path, monkeypatch)
    sync(sdir)
    calls = []
    monkeypatch.setattr(ask.subprocess, "run", lambda *a, **k: calls.append(a) or pytest.fail("provider call"))
    monkeypatch.setattr(ask.subprocess, "Popen", lambda *a, **k: calls.append(a) or pytest.fail("provider call"))
    for fts in (False, True):
        flag(monkeypatch, fts)
        assert str(root / NORA) in found(ASK, sdir, capsys, monkeypatch)
    assert calls == []
