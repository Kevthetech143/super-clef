"""superclef connect / disconnect end to end on made-up notes: the pointer, the registry row, the prepared copy and the
prepare-cache files all go; the original notes stay.   python3 -m pytest skills/super-jev/tests/test_disconnect.py -q"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent


def _run(env, *args):
    return subprocess.run([sys.executable, str(SKILL / "prepare_bulk.py"), *args], env=env, capture_output=True, text=True)


def test_disconnect_removes_everything_the_connect_made(tmp_path):
    state, notes = tmp_path / "state", tmp_path / "notes"
    notes.mkdir()
    (notes / "garden.md").write_text("# Garden plan\n\nWe plant tomatoes in May.\n")
    env = {**os.environ, "SUPERJEV_STATE_DIR": str(state), "SUPERJEV_BIN_DIR": str(tmp_path / "bin")}
    assert subprocess.run([sys.executable, str(SKILL / "setup.py")], env=env, capture_output=True).returncode in (0, 1)
    r = _run(env, "--root", str(notes), "--pointer", "garden", "--principal", "me", "--writer", "builtin")
    assert r.returncode == 0, r.stdout + r.stderr
    mem = state / "_memory"
    assert "garden" in json.loads((mem / "registry.json").read_text())["datasets"]
    assert (state / "prepare-cache" / "garden.json").is_file()

    r = _run(env, "--disconnect", "--pointer", "garden")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads((mem / "registry.json").read_text())["datasets"] == {}
    assert sqlite3.connect(mem / "memory.sqlite3").execute("select name from pointers").fetchall() == []
    assert not list((state / "prepare-cache").glob("garden*")) and not list(mem.glob(".prepared-*"))
    assert (notes / "garden.md").is_file()

    again = _run(env, "--disconnect", "--pointer", "garden")
    assert again.returncode == 1 and "not connected" in again.stdout
