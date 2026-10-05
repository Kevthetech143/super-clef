#!/usr/bin/env python3
"""Eval-30 (2026-10-05): a stale set with no prepare-cache (a path-connected set) vanished from Clef's
search. Its rows come from the engine's `sources`, which refused a stale pointer, so the set had no
rows at all while the trace said "searched as of its last refresh". Now `sources` takes lastGood (as
navigate does): the set's last good file list, labelled stale, so its unchanged files stay searchable.
Real memory runtime (cli.run over a tmp db/registry); no network, no judge.

    python3 -m pytest skills/super-jev/tests/test_stale_set_last_good_rows.py -q
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
EXP = SKILL.parent.parent / "experiments" / "verified-pointer-memory"
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(EXP))
import cli  # noqa: E402

spec = importlib.util.spec_from_file_location("ask_last_good_rows", SKILL / "ask.py")
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)


def _setup(tmp_path, monkeypatch):
    """A path-connected set 'notes' (no prepare-cache) of three notes, over the real runtime."""
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", tmp_path / "cache")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"db": "answers.sqlite", "registry": "registry.json"}))
    config = cli.load_config(cfg)
    requests = []

    def memory(req):
        requests.append(req)
        try:
            return cli.run(req, config)
        except ValueError as e:
            return {"status": "error", "reason": str(e)}

    monkeypatch.setattr(ask, "memory", memory)
    folder = tmp_path / "notes"
    folder.mkdir()
    files = {"tried": folder / "tried.md", "traps": folder / "traps.md", "log": folder / "log.md"}
    files["tried"].write_text("# Tried\nWe tried the cache warmer on the build box; it did not help.\n")
    files["traps"].write_text("# Traps\nRelease traps: the tag must match the package version.\n")
    files["log"].write_text("# Log\nOlder entries about the deploy.\n")
    req = {"action": "connect", "pointer": "notes", "principals": ["me"],
           "sources": [{"path": str(p), "description": name} for name, p in files.items()]}
    preview = memory(req)
    assert memory({**req, "reviewed": True, "sources": preview["sources"]})["status"] == "registered"
    return memory, files, requests


def _rows(memory, tmp_path):
    panel = memory({"action": "panel", "principal": "me"})
    gens = {r["pointer"]: r.get("generation") for r in panel["pointers"]}
    sdir = tmp_path / "state"
    sdir.mkdir(exist_ok=True)
    return ask.load_local_rows(sdir, "me", ["notes"], gens)


def _found(question):
    return [p for _s, p, _ptr in ask.word_search(question, ["notes"])]


def test_a_stale_set_is_still_searched_from_its_last_good_file_list(tmp_path, monkeypatch):
    memory, files, requests = _setup(tmp_path, monkeypatch)
    files["log"].write_text("# Log\nA note written minutes ago.\n")  # one file changed: the set is stale
    assert memory({"action": "sources", "pointer": "notes", "principal": "me"})["status"] == "preparation-required"
    assert _rows(memory, tmp_path) == {"notes": 3}
    assert any(r.get("action") == "sources" and r.get("lastGood") is True for r in requests)
    # Its unchanged files answer.
    assert os.path.abspath(files["tried"]) in _found("did we try the cache warmer")
    assert os.path.abspath(files["traps"]) in _found("release traps tag package version")
    # Labelled stale: the listing says which file changed since the set's last refresh.
    listed = memory({"action": "sources", "pointer": "notes", "principal": "me", "lastGood": True})
    assert listed["status"] == "ok"
    assert listed["stale"] == {"status": "preparation-required",
                               "changed": [os.path.abspath(files["log"])], "missing": []}


def test_a_deleted_file_is_not_listed(tmp_path, monkeypatch):
    memory, files, _ = _setup(tmp_path, monkeypatch)
    files["log"].unlink()
    assert _rows(memory, tmp_path) == {"notes": 2}
    listed = memory({"action": "sources", "pointer": "notes", "principal": "me", "lastGood": True})
    assert listed["stale"]["missing"] == [os.path.abspath(files["log"])]
    assert sorted(s["originalPath"] for s in listed["sources"]) == sorted(
        os.path.abspath(files[n]) for n in ("tried", "traps"))


def test_a_fresh_set_is_unchanged(tmp_path, monkeypatch):
    memory, files, _ = _setup(tmp_path, monkeypatch)
    assert _rows(memory, tmp_path) == {"notes": 3}
    assert os.path.abspath(files["tried"]) in _found("did we try the cache warmer")
    plain = memory({"action": "sources", "pointer": "notes", "principal": "me"})
    last_good = memory({"action": "sources", "pointer": "notes", "principal": "me", "lastGood": True})
    assert plain == last_good and "stale" not in plain


def test_another_principal_is_still_denied(tmp_path, monkeypatch):
    memory, files, _ = _setup(tmp_path, monkeypatch)
    files["log"].write_text("changed\n")
    assert memory({"action": "sources", "pointer": "notes", "principal": "intruder",
                   "lastGood": True})["status"] == "access-denied"


def test_the_stale_hint_says_a_replay_failed_only_when_one_did(tmp_path, monkeypatch):
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ask, "memory", lambda req: {"status": "ok"})  # a recorded connect recipe
    monkeypatch.setattr(ask.auto_heal, "last_refresh_error", lambda *a, **k: "")
    hint = ask.refresh_hint("notes", "me", "preparation-required")
    assert "failed" not in hint and "recorded connect recipe" in hint
    monkeypatch.setattr(ask.auto_heal, "last_refresh_error", lambda *a, **k: "recipe replay failed (refused)")
    hint = ask.refresh_hint("notes", "me", "preparation-required")
    assert "replaying its connect recipe failed: recipe replay failed (refused)" in hint


def test_a_stale_set_the_index_holds_no_file_list_for_is_searched_by_todays_path(tmp_path):
    # An index built before lastGood: the updater skipped the stale set (entries NULL), so serving it from the
    # index searched none of its files.
    from file_index import FileIndex
    idx = FileIndex("me", tmp_path / "index.sqlite")
    idx.set_panel([{"pointer": "notes", "snapshotStatus": "preparation-required", "generation": 1},
                   {"pointer": "view", "snapshotStatus": "available", "generation": 1}])
    assert ask.pointer_fallbacks(idx, {"notes", "view"}, None) == {"notes": "stale, its files not in the index"}
