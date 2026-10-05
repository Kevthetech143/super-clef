"""clef_client: short ssh ControlPath for a long HOME, and the SUPERCLEF_CLEF_HOST name when run directly."""
import os
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "lib"))
sys.path.insert(0, str(SKILL))
import clef_client  # noqa: E402

SOCK_MAX = 104


def _control_path(cmd):
    return next(a for a in cmd if a.startswith("ControlPath=")).split("=", 1)[1].replace("%C", "0" * 40)


def test_long_home_gets_a_short_control_path(tmp_path, monkeypatch):
    home = tmp_path / ("very-long-home-name-" * 6)
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "user@made-up-host")
    cp = _control_path(clef_client._ssh_cmd("true"))
    assert len(cp) < SOCK_MAX
    assert cp.startswith(f"/tmp/scl-{os.getuid()}/")
    assert (os.stat(os.path.dirname(cp)).st_mode & 0o777) == 0o700


def test_short_home_keeps_ssh_dir(monkeypatch):
    import tempfile
    tmp_path = Path(tempfile.mkdtemp(prefix="h", dir="/tmp"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SUPERJEV_CLEF_HOST", "user@made-up-host")
    cp = _control_path(clef_client._ssh_cmd("true"))
    assert cp.startswith(str(tmp_path / ".ssh"))


def test_run_directly_reads_superclef_host():
    code = "import clef_client;print(clef_client.host())"
    env = {"PATH": "/usr/bin:/bin", "SUPERCLEF_CLEF_HOST": "me@made-up-host"}
    out = subprocess.run([sys.executable, "-c", code], cwd=SKILL / "lib", env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "me@made-up-host", out.stderr
