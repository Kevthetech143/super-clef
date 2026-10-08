import json
import os
import sys
from pathlib import Path

import pytest


def _scrub_callers_settings():
    """The suite gives the same result whatever the caller's shell exports. Before any test module
    loads, clear the product's own settings: every SUPERJEV_* except SUPERJEV_TEST_* (developer test
    knobs), every judge profile's key and url variable, and SWEEP_BATCH (the one product setting without
    the prefix). The names come from judge_profiles.json, read directly: importing judge_profile first
    would read SUPERJEV_JUDGE before it is cleared. test/clean-env.ts is the same rule for npm test."""
    profiles = json.loads((Path(__file__).resolve().parent.parent / "judge_profiles.json").read_text())["profiles"]
    names = {"SWEEP_BATCH"}
    for profile in profiles.values():
        names.update(v for v in (profile.get("key_env"), profile.get("api_url_env")) if v)
    names.update(k for k in os.environ if k.startswith("SUPERJEV_") and not k.startswith("SUPERJEV_TEST_"))
    for name in names:
        os.environ.pop(name, None)


_scrub_callers_settings()
# Super Clef's default judge is clef (a live call to the clef machine). The Jev-shaped suites take the Jev profile as the
# default through this test knob (SUPERJEV_TEST_* survives the scrub) and run it with fake doors; the clef judge has its own stub-judge tests (test_clef_judge.py), which select it themselves.
os.environ["SUPERJEV_TEST_DEFAULT_JUDGE"] = "typesafe-jev"
# The prepare-cache lives in the state dir and its modules bind that path at import. Import them once with a
# throwaway state dir (so the suite never touches the real cache), then clear it again: the suite still starts
# from a clean environment, and a test that sets SUPERJEV_STATE_DIR itself still wins for its own run.
import tempfile  # noqa: E402
os.environ["SUPERJEV_STATE_DIR"] = tempfile.mkdtemp(prefix="superclef-test-state-", dir="/tmp")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import watched, prepare_bulk, refresh_changed  # noqa: E402,F401
os.environ.pop("SUPERJEV_STATE_DIR")
# The stub-judge suites fake the one-shot clef transport, so the warm daemon path is off for them from the
# first import (test_clef_warm.py turns it on with fakes).
_SKILL = str(Path(__file__).resolve().parent.parent)
sys.path[:0] = [_SKILL, os.path.join(_SKILL, "lib")]
import clef_client  # noqa: E402
clef_client.WARM = False

def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs the clef machine reachable; runs only with SUPERJEV_TEST_LIVE=1")
    config.addinivalue_line("markers", "real_toc: keeps the real TOC search (no replay of faked navigate candidates)")
    config.addinivalue_line("markers", "real_code_ask: uses the real fleet jev lib; skips when the lib file is absent")


@pytest.fixture(autouse=True)
def _one_call_per_pointer(monkeypatch):
    """These suites fake one navigate/confirm call per pointer or file: the path
    SUPERJEV_BATCH_JEV=0 keeps and a failed batch falls back to. The batched path
    has its own tests (test_batch_jev.py), which turn it back on."""
    monkeypatch.setenv("SUPERJEV_BATCH_JEV", "0")


@pytest.fixture(autouse=True)
def _no_skill_catalog(monkeypatch):
    """Lookups never shell out to the live skills connector in tests; test_stale_quiet_and_skills.py
    turns it on with a faked catalog."""
    monkeypatch.setenv("SUPERJEV_SKILLS", "0")


@pytest.fixture(autouse=True)
def _no_live_shared_list(monkeypatch, tmp_path):
    """prepare_bulk shares the deployment's shared-pointers.json after a connect; tests never read
    the live list. test_share_pointers.py points it at its own file."""
    monkeypatch.setenv("SUPERJEV_SHARED_POINTERS", str(tmp_path / "no-shared-pointers.json"))


@pytest.fixture(autouse=True)
def _no_new_file_scan(monkeypatch):
    """Lookups never start the background new-file scan in tests; test_auto_heal.py calls it directly."""
    monkeypatch.setenv("SUPERJEV_NEW_FILE_SCAN", "0")


@pytest.fixture(autouse=True)
def _no_live_chat_config_or_launcher(monkeypatch, tmp_path):
    """--uninstall also removes the chat CLI's config (it holds an API key) and its launcher.
    No test may reach the real ones: both folders point into tmp unless a test sets its own."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg-config"))
    monkeypatch.setenv("SUPERJEV_BIN_DIR", str(tmp_path / "no-bin"))


@pytest.fixture(autouse=True)
def _toc_read_list_replays_old_routing(request, monkeypatch):
    """The zoom now picks the read list (routing asks Jev nothing), for questions and claims. These suites were
    written when the read list came from each pointer's navigate candidates, which they fake: stand in for the
    zoom by listing those faked candidates (best first) that the zoom's store holds, so what they test (ranking,
    merging, filters and messages after the read list) is unchanged. test_toc_search.py, test_zoom_to_part.py and
    test_zoom.py (and tests marked real_toc) exercise the real zoom and are left alone."""
    if request.module.__name__.split(".")[-1] in ("test_toc_search", "test_zoom_to_part", "test_zoom") or request.node.get_closest_marker("real_toc"):
        return
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import zoom

    real_run = zoom.run

    def replay(question, store, hits, ask_hooks, joins=(), word=None, judge_free=False):
        if judge_free:  # the clef judge never routes through navigate: its suites run the real judge-free zoom
            return real_run(question, store, hits, ask_hooks, joins=joins, word=word, judge_free=True)
        caller = sys._getframe(1)
        mem, principal = caller.f_globals["memory"], caller.f_locals.get("principal")
        rows = []
        routed_now = set(caller.f_locals.get("nav_ptrs") or [])  # sets the ask itself routed: their files are `joins`
        for ptr in [p_ for p_ in caller.f_locals.get("search_pointers") or [] if p_ not in routed_now]:
            try:
                out = mem({"action": "navigate", "pointer": ptr, "principal": principal, "question": question,
                           "lastGood": True})
            except Exception:  # noqa: BLE001 -- a suite that fakes no navigate has no routed candidates
                continue
            if isinstance(out, dict) and out.get("status") == "candidates":
                rows += [(c["score"], c["originalPath"]) for c in out.get("candidates") or []
                         if isinstance(c, dict) and store.has(c.get("originalPath"))]
        routed = [p for _s, p in sorted(rows, key=lambda r: -r[0])]
        files = list(dict.fromkeys(routed + list(joins) + [p for _s, p, _ptr in hits]))
        top = [(p, sc) for sc, p in sorted(rows, key=lambda r: -r[0])]
        return files, [], {"pick": {"top": top}}

    monkeypatch.setattr(zoom, "run", replay)

# Tests that guard routing calls a question no longer makes. Skipped with the reason, never deleted.
_DROPPED = "dropped on purpose: no routing calls on question path"
_OLD_ROUTING = {
    "test_content_cost.py::test_pointer_without_any_question_word_is_not_routed": _DROPPED,
    "test_content_cost.py::test_synonym_keeps_the_pointer": _DROPPED,
}


def pytest_collection_modifyitems(items):
    for item in items:
        reason = _OLD_ROUTING.get(item.nodeid.split("tests/")[-1])
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))
