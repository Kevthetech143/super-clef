#!/usr/bin/env python3
"""Cold vs warm timing of the clef judge call on the 5-question timing set (wall clock only, no scores).

    python3 scripts/clef-warm-timing.py [--set PATH] [--oneshot] [--keep]

Each question becomes one short judge package (about 600 tokens): the question plus the opening of its gold
files and one decoy, as a listwise choice, sent through clef_client.ask (the same call Super Clef makes for its
confirm step). The local search that picks the candidates is not part of this timing (about 10 s, unchanged).
Default: stops any warm daemon, then runs the 5 in order: the first pays daemon start + model load, the rest are
warm; the daemon is stopped at the end unless --keep. --oneshot runs the same 5 with the warm path off (today's
path: ssh + model load every call). One question at a time: one clef process on the clef machine at a time.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "skills", "super-jev"), os.path.join(ROOT, "skills", "super-jev", "lib")]
SET = os.environ.get("TIMING_SET", "timing-set.jsonl")
if "--set" in sys.argv:
    SET = sys.argv[sys.argv.index("--set") + 1]
ONESHOT = "--oneshot" in sys.argv
os.environ["SUPERJEV_CLEF_WARM"] = "0" if ONESHOT else "1"
import clef_client  # noqa: E402
import judge_profile  # noqa: E402

clef_client.PROFILE = judge_profile.load("clef")
rows = [json.loads(l) for l in open(SET) if l.strip()]
OPENING = 450  # characters of each file's opening: keeps the package near the 630-token short-call budget


def package(i, row):
    files = [g for g in row["gold"] if os.path.exists(g)][:2]
    decoy = rows[(i + 1) % len(rows)]["gold"][0]
    files.append(decoy)
    state, criteria = "", {}
    for n, f in enumerate(files, 1):
        text = open(f, errors="replace").read()[:OPENING].replace("\n", " ")
        state += f"[f{n}] {os.path.basename(f)}: {text}\n"
        criteria[f"f{n}"] = f"file f{n}"
    q = {"pick": {"type": "choice", "instructions": f"Which file best answers: {row['question']}", "criteria": criteria}}
    return state, q


if not ONESHOT:
    clef_client.stop_transport()
print("| # | question | secs | mode |\n|---|---|---|---|")
times = []
for i, r in enumerate(rows):
    state, q = package(i, r)
    t = time.time()
    res = clef_client.ask(state, q)
    secs = time.time() - t
    times.append(secs)
    mode = "one-shot" if ONESHOT else ("cold: start + load" if i == 0 else "warm")
    print(f"| {i + 1} | {r['question'][:50]} | {secs:.1f} | {mode}, judge {res['secs']}, warm={res['warm']} |", flush=True)
print(f"first {times[0]:.1f} s; rest mean {sum(times[1:]) / max(len(times) - 1, 1):.1f} s; all mean {sum(times) / len(times):.1f} s")
if not ONESHOT and "--keep" not in sys.argv:
    clef_client.stop_transport()
