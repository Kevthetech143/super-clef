#!/usr/bin/env python3
"""Under the clef profile, --writer auto resolves to builtin; other profiles keep the old behavior.

    python3 -m pytest skills/super-jev/tests/test_clef_writer_default.py -q
"""
import importlib.util
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prepare_bulk_clef_writer", SKILL / "prepare_bulk.py")
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)
import judge_profile  # noqa: E402


def _banner(tmp_path, monkeypatch, capsys, profile, claude):
    root = tmp_path / "notes"
    root.mkdir()
    (root / "a.md").write_text("# Travel\n\n## Hotels\nUp to 220 dollars per night.\n")
    monkeypatch.setattr(pb, "JUDGE_PROFILE", judge_profile.load(profile))
    monkeypatch.setattr(pb, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pb.shutil, "which", lambda n: "/bin/claude" if claude else None)
    monkeypatch.delenv("SUPERJEV_WRITER_COMMAND", raising=False)
    monkeypatch.setattr(sys, "argv", ["prepare_bulk.py", "--root", str(root), "--pointer", "notes",
                                      "--principal", "me", "--no-connect"])
    pb.main()
    return capsys.readouterr().out


def test_clef_auto_is_builtin_even_with_claude_present(tmp_path, monkeypatch, capsys):
    out = _banner(tmp_path, monkeypatch, capsys, "clef", claude=True)
    assert "writer: builtin" in out


def test_typesafe_jev_auto_keeps_old_behavior(tmp_path, monkeypatch, capsys):
    out = _banner(tmp_path, monkeypatch, capsys, "typesafe-jev", claude=True)
    assert "writer: claude -p --model haiku" in out
