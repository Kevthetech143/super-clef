#!/usr/bin/env python3
"""Super Clef finds sets that have no prepare-cache (a manual note from --add, a path-connected set) through
local rows built from their reviewed sources, and never routes them through navigate (clef has no
implementation of it). A set with no local rows is named in the trace, not called available.
Fake engine, made-up notes, no network, no clef machine.

    python3 -m pytest skills/super-jev/tests/test_clef_uncached_sets.py -q
"""
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import ask  # noqa: E402


class Engine:
    """A tiny in-memory registry: connect (preview, then reviewed) registers a set; navigate is a failure."""
    def __init__(self):
        self.sets, self.calls = {}, []

    def __call__(self, req):
        self.calls.append(req["action"])
        act, ptr = req["action"], req.get("pointer")
        if act == "panel":
            return {"pointers": [{"pointer": p, "snapshotStatus": "available", "generation": f"g-{p}"} for p in self.sets]}
        if act == "cached":
            return {"status": "cache-miss", "checked": []}
        if act == "connect":
            srcs = req["sources"]
            if not req.get("reviewed"):
                return {"status": "preparation-required", "sources": [{"path": s["path"], "sha256": "x"} for s in srcs]}
            self.sets[ptr] = [{"originalPath": s["path"], "contentSHA": ask.sha256_file(Path(s["path"])),
                               "description": s.get("description", "")} for s in srcs]
            return {"status": "registered", "sources": [{"id": "file:1", "originalPath": s["path"]} for s in srcs]}
        if act == "sources":
            return {"status": "ok", "sources": self.sets.get(ptr, [])}
        if act == "search":  # the --add save step: refused under clef, as in production
            return {"status": "error", "reason": "judge"}
        raise AssertionError(f"unexpected engine call: {req}")  # navigate must never be reached


@pytest.fixture
def clef(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    eng = Engine()
    monkeypatch.setattr(ask.prepare_bulk, "CACHE_DIR", cache)
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setattr(ask, "memory", eng)
    monkeypatch.setattr(ask, "confirm", lambda q, ps: ({p: 0.9 for p in ps}, set(), None, {}))
    ask._CLEF.update(low_trust=set(), leans_none=False, strong_none=False)
    ask._STAGE.clear()
    return eng, tmp_path / "state"


def _register(eng, ptr, path, desc="note"):
    pv = eng({"action": "connect", "pointer": ptr, "sources": [{"path": str(path), "description": desc}]})
    assert pv["status"] == "preparation-required"
    eng({"action": "connect", "pointer": ptr, "reviewed": True, "sources": [{"path": str(path), "description": desc}]})


def test_note_added_with_add_is_found_by_the_next_ask(clef, capsys):
    eng, sdir = clef
    q = "what is the orchid greenhouse gate code"
    rc = ask.add_manual("alice", q, "The orchid greenhouse gate code is 4417.", None, sdir)
    assert "pointer" in capsys.readouterr().out and ("registered" in " ".join(eng.calls) or eng.sets)
    assert len(eng.sets) == 1
    del rc  # saving is refused under clef (gap B stays off); only the registration matters here
    ask._STAGE.clear()
    rc = ask.lookup(q, "alice", sdir)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "navigate" not in eng.calls
    assert "Navigation failed" not in out and "not searched" not in out
    assert "manual" in out


def test_path_connected_set_yields_its_file(clef, tmp_path, capsys):
    eng, sdir = clef
    f = tmp_path / "otter.md"
    f.write_text("The otter feeding schedule: fish at noon, shrimp at dusk.\n")
    _register(eng, "alice-recipe", f)
    rc = ask.lookup("when is the otter fed fish", "alice", sdir)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert str(f) in out
    assert "navigate" not in eng.calls and "Navigation failed" not in out


def test_set_with_no_local_rows_is_reported_not_available(clef, tmp_path, capsys):
    eng, sdir = clef
    f = tmp_path / "heron.md"
    f.write_text("The heron nests by the pond.\n")
    _register(eng, "alice-notes", f)
    eng.sets["alice-empty"] = []
    ask._STAGE.clear()
    ask.lookup("anything about the empty set", "alice", sdir)
    capsys.readouterr()
    assert "navigate" not in eng.calls
    assert ask._STAGE["routing_fallback"] == ["alice-empty: no local rows"]
    ask.connection_status("alice")
    assert "alice-empty: registered, but no files to search" in capsys.readouterr().out


def test_path_only_set_yields_its_file_without_routing(clef, tmp_path, capsys):
    eng, sdir = clef
    f = tmp_path / "badger.md"
    f.write_text("The badger sett has three entrances, two by the oak.\n")
    eng.sets["alice-pathonly"] = [{"path": str(f), "contentSHA": ask.sha256_file(f), "description": "note"}]
    rows = ask.source_rows("alice", "alice-pathonly")
    assert list(rows) == [str(f)]
    rc = ask.lookup("how many entrances does the badger sett have", "alice", sdir)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert str(f) in out
    assert "navigate" not in eng.calls
    assert not ask._STAGE.get("routing_fallback")
