"""SUPERCLEF_X is the public name for SUPERJEV_X: new name wins, old names keep working."""
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]


def _run(env, code):
    full = {"PATH": "/usr/bin:/bin", **env}
    return subprocess.run([sys.executable, "-c", code], cwd=SKILL, env=full, capture_output=True, text=True).stdout.strip()


def test_new_name_wins_and_old_name_still_works():
    code = "import superclef_env,os;print(os.environ.get('SUPERJEV_STATE_DIR'),os.environ.get('SUPERJEV_PRINCIPAL'),os.environ.get('SUPERJEV_JUDGE'))"
    out = _run({"SUPERCLEF_STATE_DIR": "/new", "SUPERJEV_STATE_DIR": "/old", "SUPERJEV_PRINCIPAL": "me"}, code)
    assert out == "/new me None"


def test_every_entrypoint_imports_it_before_local_modules():
    for name in ("ask", "setup", "prepare_bulk", "clef_media", "refresh_changed", "auto_heal"):
        src = (SKILL / f"{name}.py").read_text()
        assert "import superclef_env" in src, name
