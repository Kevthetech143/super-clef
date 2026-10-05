"""Frozen live media tests: made-up images and clips (PIL, ffmpeg), judged by clef on the clef machine over ssh.
Run with: npm run test:media   (needs the clef machine reachable; one clef process at a time).
Cases: image present, image text present, video motion present, one absent. Nothing may be left on the clef machine."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "skills" / "super-jev"), str(HERE.parents[1] / "skills" / "super-jev" / "lib")]
import clef_client  # noqa: E402
import clef_media  # noqa: E402
import media_fixtures  # noqa: E402


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    t = tmp_path_factory.mktemp("media")
    os.environ["SUPERJEV_STATE_DIR"] = str(t / "state")
    os.environ["SUPERJEV_PRINCIPAL"] = "media-test"
    paths = media_fixtures.make(str(t / "lib"))
    assert len(clef_media.connect([str(t / "lib")])) == 5
    return paths


def _ask(q):
    r = clef_media.ask(q, top=5)
    assert r["outcome"] != "error", r
    assert r["checked"] == 5
    return r


def test_image_shape_present(lib):
    r = _ask("a red triangle")
    assert r["outcome"] == "found" and r["items"][0]["path"] == lib["red_triangle"]


def test_image_text_present(lib):
    r = _ask("an image with the word STOP written on it")
    assert r["outcome"] == "found" and r["items"][0]["path"] == lib["stop_sign"]


def test_video_motion_present(lib):
    r = _ask("a video where a red square moves across the screen")
    assert r["outcome"] == "found" and r["items"][0]["path"] == lib["red_square_moving"]


def test_absent_is_not_found(lib):
    r = _ask("a photo of a yellow elephant")
    assert r["outcome"] == "not-found" and r["items"] == []


def test_nothing_left_on_the_mini():
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", clef_client.host(),
                        'ls -d "$HOME"/.clefcall.* 2>/dev/null | wc -l'], capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip() == "0"
