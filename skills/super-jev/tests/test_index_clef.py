#!/usr/bin/env python3
"""The index read path under the clef judge profile: the same top 5 with the index on as off (the TOC shortlist
ranks by idf over the shortlist, not the whole corpus), and a reviewed view is never given file rows.
Made-up files and stubs, no network.

    python3 -m pytest skills/super-jev/tests/test_index_clef.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_index_read_path as t  # noqa: E402

pytestmark = pytest.mark.real_toc
ask = t.ask


def test_clef_profile_same_top5_with_the_index_on_as_off(tmp_path, monkeypatch, capsys):
    notes, names, sdir = t.build(tmp_path, monkeypatch, 80)
    t.Rig(monkeypatch, notes, names)
    monkeypatch.setattr(ask, "CLEF", True)
    t.flag(monkeypatch, False)
    base = [t.top5(t.ask_it(q, sdir, capsys)[1]) for q, *_ in t.PLANTED]
    t.sync(sdir)
    t.flag(monkeypatch, True)
    got = [t.top5(t.ask_it(q, sdir, capsys)[1]) for q, *_ in t.PLANTED]
    assert got == base
    assert all(top and top[0].endswith(fname) for top, (_q, fname, _l) in zip(got, t.PLANTED))
    assert ask._STAGE["index"]["used"] is True


def test_a_reviewed_view_gets_a_panel_row_and_no_file_rows(tmp_path, monkeypatch, capsys):
    notes, names, sdir = t.build(tmp_path, monkeypatch, 20)
    rig = t.Rig(monkeypatch, notes, names)
    real = rig.memory

    def memory(req):
        out = real(req)
        if req["action"] == "panel":
            out["pointers"].append({"pointer": "a-view", "snapshotStatus": "ready", "generation": 1,
                                    "viewOriginals": [str(notes / "p0" / "zorblax.md")]})
        return out
    monkeypatch.setattr(ask, "memory", memory)
    monkeypatch.setattr(ask, "engine_visible", lambda principal: set(names) | {"a-view"})
    monkeypatch.setattr(ask, "engine_generations", lambda: None)
    t.sync(sdir)
    from file_index import FileIndex
    idx = FileIndex(t.PRINCIPAL, sdir / "index.sqlite")
    try:
        assert idx.db.execute("SELECT COUNT(*) FROM files WHERE pointer='a-view'").fetchone()[0] == 0
        assert any(r["pointer"] == "a-view" and r.get("viewOriginals") for r in idx.panel_rows())
    finally:
        idx.close()
