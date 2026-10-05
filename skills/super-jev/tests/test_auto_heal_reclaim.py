#!/usr/bin/env python3
"""A queued heal whose lock holder is gone is reclaimable: the next ask starts a drain for it,
even when the ask's own sets only cooled down. Popen is faked, so no drain really runs.

    python3 -m pytest skills/super-jev/tests/test_auto_heal_reclaim.py -q
"""
import time

from test_auto_heal import _add_pointer, _setup, ah


def _orphan(calls_cache, monkeypatch):
    """`stuck` is queued for a refresh; the lock that was to drain it names a dead pid."""
    calls, cache_dir = calls_cache
    _add_pointer(cache_dir, "stuck")
    _add_pointer(cache_dir, "asked")
    now = time.time()
    ah._queue("agent", "stuck", "refresh")
    ah._mark("agent", "asked", now)  # the set this ask is about is cooling down
    ah.STATE_DIR.mkdir(parents=True, exist_ok=True)
    ah._lock_path("agent", "stuck").write_text(
        '{"pid": 999999, "ts": %f, "token": "gone", "drain": true}' % now)
    return calls


def test_an_ask_that_only_cooled_down_still_reclaims_an_orphaned_queue_item(tmp_path, monkeypatch):
    calls = _orphan(_setup(tmp_path, monkeypatch, name="moving"), monkeypatch)
    out = ah.heal_in_background_many(["asked"], "agent")
    assert out == {"asked": "cooldown"}  # the ask's own answer is unchanged
    assert len(calls) == 1 and "--drain" in calls[0][2]  # a drain was started for the orphan
    assert ah._lock_path("agent", "stuck").exists() and "gone" not in ah._lock_path("agent", "stuck").read_text()


def test_a_live_holder_is_not_reclaimed(tmp_path, monkeypatch):
    import os
    calls = _orphan(_setup(tmp_path, monkeypatch, name="moving"), monkeypatch)
    ah._lock_path("agent", "stuck").write_text(
        '{"pid": %d, "ts": %f, "token": "live", "drain": true}' % (os.getpid(), time.time()))
    assert ah.heal_in_background_many(["asked"], "agent") == {"asked": "cooldown"}
    assert calls == []


def test_a_queue_item_that_cannot_run_yet_starts_no_drain(tmp_path, monkeypatch):
    calls, cache_dir = _setup(tmp_path, monkeypatch, name="moving")
    _add_pointer(cache_dir, "asked")
    ah._queue("agent", "asked", "refresh")
    ah._mark("agent", "asked", time.time())  # _mark drops it from the queue; queue it again, cooling
    ah._queue("agent", "asked", "refresh")
    assert ah.heal_in_background_many(["asked"], "agent") == {"asked": "cooldown"}
    assert calls == []
