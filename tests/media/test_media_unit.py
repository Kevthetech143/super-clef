"""Offline media tests: connect records pointers only, the cap ranks by hint words, the private vaults are refused,
the call goes through a stub transport. No clef machine, no network.   python3 -m pytest tests/media/test_media_unit.py -q"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / "skills" / "super-jev"), str(HERE.parents[1] / "skills" / "super-jev" / "lib")]
import clef_media  # noqa: E402
import media_fixtures  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERJEV_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SUPERJEV_PRINCIPAL", "t")
    return media_fixtures.make(str(tmp_path / "lib"))


def test_connect_records_pointer_only(env):
    added = clef_media.connect([os.path.dirname(env["red_triangle"])])
    assert len(added) == 5
    reg = clef_media.load()
    m = reg[env["red_triangle"]]
    assert m["kind"] == "image" and m["size"] == os.path.getsize(env["red_triangle"])
    assert m["sha256"] == hashlib.sha256(open(env["red_triangle"], "rb").read()).hexdigest()
    assert reg[env["red_square_moving"]]["kind"] == "video"
    assert set(m) == {"kind", "sha256", "size", "hint", "mtime"}  # no text index, no content


def test_private_vault_refused(env, monkeypatch, tmp_path):
    vault = tmp_path / "profile"
    vault.mkdir()
    (vault / "x.png").write_bytes(open(env["red_triangle"], "rb").read())
    monkeypatch.setattr(clef_media, "PRIVATE", [str(vault)])
    assert clef_media.connect([str(vault)]) == []


def test_cap_prefers_hint_words(env, tmp_path):
    d = tmp_path / "named"
    d.mkdir()
    for n in ("harbor_sunset.png", "invoice_scan.png", "cat.png", "dog.png", "tree.png"):
        (d / n).write_bytes(open(env["red_triangle"], "rb").read())
    (d / "dog.txt").write_text("receipt from the vet")
    clef_media.connect([str(d)])
    top = clef_media.candidates("find the vet receipt", clef_media.load(), 2)
    assert os.path.basename(top[0][0]) == "dog.png" and len(top) == 2


def test_ask_stub_transport_labels_and_cleanup(env, monkeypatch):
    clef_media.connect([os.path.dirname(env["red_triangle"])])
    seen = {}

    def fake(body, timeout):
        req = json.loads(body)
        seen["n"] = len(req["items"])
        res = [{"id": it["id"], "p_yes": 0.95 if it["id"] == env["red_triangle"] else 0.05, "secs": 1.0} for it in req["items"]]
        return clef_media.MARK + json.dumps({"results": res, "load": 3.0}) + "\n", "", 0

    monkeypatch.setattr(clef_media, "transport", fake)
    r = clef_media.ask("red triangle", top=5)
    assert seen["n"] == 5 and r["outcome"] == "found" and r["items"][0]["path"] == env["red_triangle"]
    assert [i["label"] for i in r["items"]] == ["confirmed-by-clef"]
    monkeypatch.setattr(clef_media, "transport", lambda b, t: (clef_media.MARK + json.dumps({"results": [{"id": json.loads(b)["items"][0]["id"], "p_yes": 0.1, "secs": 1}], "load": 1}), "", 0))
    assert clef_media.ask("yellow elephant", top=1)["outcome"] == "not-found"


def test_unreachable_is_an_error_not_a_not_found(env, monkeypatch):
    clef_media.connect([os.path.dirname(env["red_triangle"])])
    monkeypatch.setattr(clef_media, "transport", lambda b, t: ("", "ssh: connect failed", 255))
    assert clef_media.ask("anything")["outcome"] == "error"
