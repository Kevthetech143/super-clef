#!/usr/bin/env python3
"""An ask never reconnects a stale set itself (live 2026-10-05: 12 stale sets, 139 s; 70 stale sets, 103 s).
Its time must not grow with the number of stale sets: a stale set is searched from its last prepared file
list, or reported as refreshing; ALL stale sets go to the heal side in ONE call (one state-lock step, at most
one registry read, at most one drain). Made-up Quillbrook notes, a deliberately slow registry and lock.

    python3 -m pytest skills/super-jev/tests/test_ask_no_inline_heal.py -q
"""
import json
import threading
import time

import pytest

from test_ask_json import Q, ah, ask, clean, notes, run, world  # noqa: F401  (fixtures: clean is autouse)

REAL_TXN = ah._state_txn
REAL_BATCH = ah.heal_in_background_many  # world() stands in a canned one
SLOW = 0.3  # one fake registry read, or one state-lock step


def stale_world(tmp_path, monkeypatch, notes, n, with_list):
    """n stale sets named s0..; each has a prepared file list when `with_list`."""
    names = [f"s{i}" for i in range(n)]
    w = notes / "warranty.md"
    cache = {p: {str(w): {"pass": True, "sha256": ask.sha256_file(w), "description": "a note"}} for p in names} if with_list else {}
    rows = [{"pointer": p, "snapshotStatus": "refresh-required"} for p in names]
    world(tmp_path, monkeypatch, pointers=names, panel={"pointers": rows}, navigate=lambda p: {"status": "refresh-required" if not with_list else "no-candidates"},
          cache=cache, scores={str(w): 0.95}, lines={str(w): 4})
    return names


def slow_heal_side(tmp_path, monkeypatch, names, recipes=True):
    """The real heal side over a made-up state dir, with a slow registry and a slow state lock, counting both."""
    from test_auto_heal_fresh import Proc
    monkeypatch.setattr(ah, "STATE_DIR", tmp_path / "heal-state")
    monkeypatch.setattr(ah, "LOG_PATH", tmp_path / "heal-state" / "autoheal.log")
    monkeypatch.setattr(ah.rc, "CACHE_DIR", tmp_path / "heal-cache")  # no reports: every set heals by recipe
    Proc.launched = []
    src = tmp_path / "notes" / "r.md"
    src.parent.mkdir(exist_ok=True)
    src.write_text("# r\n")
    seen = {"reads": [], "txns": 0, "spawns": []}
    monkeypatch.setattr(ah, "heal_in_background_many", REAL_BATCH)

    def memory(req):
        seen["reads"].append(req)
        time.sleep(SLOW)
        return {"status": "ok", "recipes": {p: {"status": "ok", "recipe": {"pointer": p, "dataset": "d", "principals": ["me"], "structure": {},
                "sources": [{"path": str(src)}]}} if recipes else {"status": "no-recipe"} for p in req["pointers"]}}
    monkeypatch.setattr(ah, "_memory", memory)
    real_txn = REAL_TXN  # not a wrapper from an earlier call in the same test

    class Txn:
        def __init__(self, principal):
            self.cm = real_txn(principal)

        def __enter__(self):
            seen["txns"] += 1
            time.sleep(SLOW)
            return self.cm.__enter__()

        def __exit__(self, *a):
            return self.cm.__exit__(*a)
    monkeypatch.setattr(ah, "_state_txn", Txn)
    monkeypatch.setattr(ah, "_spawn_detached", lambda argv: seen["spawns"].append(argv) or Proc(argv))
    return seen


def ask_time(monkeypatch, capsys, *args):
    t0 = time.time()
    run(monkeypatch, capsys, *args)
    return time.time() - t0


def test_ask_time_does_not_grow_with_the_number_of_stale_sets(tmp_path_factory, monkeypatch, capsys, notes):
    """The heal side's share of an ask (the ask with the slow registry and lock, minus the same ask with an
    instant heal side, so the ask's own per-set rendering is left out) stays flat from 1 to 70 stale sets."""
    cost = {}
    for n in (1, 10, 70):
        names = stale_world(tmp_path_factory.mktemp(f"n{n}"), monkeypatch, notes, n, with_list=True)
        seen = slow_heal_side(tmp_path_factory.mktemp(f"h{n}"), monkeypatch, names)
        real = ah.heal_in_background_many
        monkeypatch.setattr(ah, "heal_in_background_many", lambda ptrs, principal, views=(): {p: "in-progress" for p in ptrs})
        ask_time(monkeypatch, capsys, Q)  # warm
        fast = ask_time(monkeypatch, capsys, Q)
        monkeypatch.setattr(ah, "heal_in_background_many", real)
        cost[n] = ask_time(monkeypatch, capsys, Q) - fast
        assert seen["txns"] == 1 and len(seen["reads"]) <= 1 and len(seen["spawns"]) == 1, n  # O(1), whatever the count
    assert cost[70] - cost[1] < 0.5, cost


def test_the_batch_does_one_lock_step_one_read_one_drain_and_names_each_set(tmp_path, monkeypatch):
    seen = slow_heal_side(tmp_path, monkeypatch, [])
    names = [f"s{i}" for i in range(70)]
    got = ah.heal_in_background_many(names, "me")
    assert seen["txns"] == 1 and len(seen["reads"]) == 1 and len(seen["spawns"]) == 1
    assert got["s0"] == "started" and set(got.values()) == {"started", "in-progress"}  # only the drain's first set really started
    assert sum(v == "started" for v in got.values()) == 1
    assert len(ah._load_state("me")["pending"]) == 70  # the rest are queued for the drain


def test_a_set_with_no_recipe_a_manual_note_and_a_view_are_told_apart(tmp_path, monkeypatch):
    seen = slow_heal_side(tmp_path, monkeypatch, [], recipes=False)
    got = ah.heal_in_background_many(["a", "b-manual-1", "c"], "me", views={"c"})
    assert got == {"a": "no-recipe", "b-manual-1": "manual", "c": "no-recipe"}
    assert not seen["spawns"] and not ah._load_state("me")["pending"]  # nothing claimed, nothing queued


def test_sets_with_no_stale_set_touch_nothing(tmp_path, monkeypatch):
    seen = slow_heal_side(tmp_path, monkeypatch, [])
    assert ah.heal_in_background_many([], "me") == {} and not seen["txns"] and not seen["reads"]


def test_cooldown_and_held_sets_spawn_nothing_and_a_failed_replay_says_so(tmp_path, monkeypatch):
    seen = slow_heal_side(tmp_path, monkeypatch, [])
    rec = ah._recipes("me", ["g", "h"])["h"]
    with ah._state_txn("me") as st:
        st["held"]["h"] = {"fp": ah._fingerprint([rec["sources"][0]["path"]], rec), "ts": ah.time.time()}
        st["retry"]["g"] = ah.time.time() + 100  # a replay that failed waits out its retry
    assert ah.heal_in_background_many(["g", "h"], "me") == {"g": "cooldown", "h": "held"}
    assert not seen["spawns"]
    ah._note_replay_failure("me", "g", False, "scope-change")
    assert "scope-change" in ah.last_refresh_error("me", "g")  # the ask says "last refresh FAILED", not "cooling down"
    ah._note_replay_failure("me", "g", True)
    assert ah.last_refresh_error("me", "g") == ""


def test_the_hourly_cap_is_not_overshot_across_sets(tmp_path, monkeypatch):
    from test_auto_heal_fresh import Proc, _setup
    from test_auto_heal_fresh import ah as real
    cache_dir, clock = _setup(tmp_path, monkeypatch, names=("a", "b", "c"), changed=True)
    with real._state_txn("tester") as st:
        st["attempts"] = [clock[0] - 10] * (real.MAX_PER_HOUR - 1)  # one slot left this hour
    monkeypatch.setattr(real, "_spawn_detached", lambda argv: Proc(argv))
    got = real.heal_in_background_many(["a", "b", "c"], "tester")
    assert sorted(got.values()) == ["rate-limited", "rate-limited", "started"]  # one slot left: one set takes it, the others wait


def test_eight_parallel_asks_start_one_drain(tmp_path, monkeypatch):
    seen = slow_heal_side(tmp_path, monkeypatch, [])
    names = [f"s{i}" for i in range(5)]
    got = []
    ts = [threading.Thread(target=lambda: got.append(ah.heal_in_background_many(names, "me"))) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(seen["spawns"]) == 1
    assert sum(v == "started" for g in got for v in g.values()) == 1  # only one ask truly started anything


# --- statuses and texts per set --------------------------------------------------------------------

def test_a_stale_set_with_a_prepared_list_still_answers(tmp_path, monkeypatch, capsys, notes):
    stale_world(tmp_path, monkeypatch, notes, 3, with_list=True)
    rc, out = run(monkeypatch, capsys, Q)
    assert rc == 0 and "warranty.md" in out
    assert "[STALE]" in out or "stale" in out


def test_a_stale_set_with_no_list_says_it_is_refreshing(tmp_path, monkeypatch, capsys, notes):
    stale_world(tmp_path, monkeypatch, notes, 2, with_list=False)
    monkeypatch.setattr(ah, "heal_in_background_many", lambda ptrs, principal, views=(): {p: "started" for p in ptrs})
    rc, out = run(monkeypatch, capsys, "--json", Q)
    obj = json.loads(out)
    assert rc != 0 and obj["outcome"] == "needs-setup"
    assert [u["healing"] for u in obj["unsearched"]] == [True, True]  # shown to the caller as "refreshing, ask again"
    assert not obj.get("files")


def test_the_ask_hands_all_its_stale_sets_over_in_one_call(tmp_path, monkeypatch, capsys, notes):
    stale_world(tmp_path, monkeypatch, notes, 4, with_list=False)
    calls = []
    monkeypatch.setattr(ah, "heal_in_background_many", lambda ptrs, principal, views=(): calls.append(sorted(ptrs)) or {p: "started" for p in ptrs})
    run(monkeypatch, capsys, Q)
    assert calls == [["s0", "s1", "s2", "s3"]]


def test_a_set_with_no_recipe_is_not_claimed_as_refreshing(tmp_path, monkeypatch, capsys, notes):
    stale_world(tmp_path, monkeypatch, notes, 1, with_list=False)
    monkeypatch.setattr(ah, "heal_in_background_many", lambda ptrs, principal, views=(): {p: "no-recipe" for p in ptrs})
    _, out = run(monkeypatch, capsys, "--json", Q)
    assert [u["healing"] for u in json.loads(out)["unsearched"]] == [False]
    assert "refreshing in the background" not in out and "refresh started" not in out


def test_a_started_heal_says_to_ask_again_in_a_minute(tmp_path, monkeypatch, capsys, notes):
    stale_world(tmp_path, monkeypatch, notes, 1, with_list=False)
    monkeypatch.setattr(ah, "heal_in_background_many", lambda ptrs, principal, views=(): {p: "started" for p in ptrs})
    _, out = run(monkeypatch, capsys, Q)
    assert "refreshing in the background; ask again in a minute" in out
