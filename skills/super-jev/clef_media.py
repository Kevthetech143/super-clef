#!/usr/bin/env python3
"""clef_media.py -- Super Clef's image and video support (a Super Clef edge: Super Jev's judge is text-only).

    superclef media connect <file-or-folder>...   record png/jpg/webp/mp4/mov files (path, sha256, size, hint words); no text index
    superclef media list
    superclef media ask "question" [--top N] [--json]

connect keeps only a pointer: sha, size, kind and a few hint words (file name, folder names, a same-name .txt/.md
note). ask picks the top few candidates by those hint words (the rest of the cap is filled newest-first so an
absent answer is still checked, not guessed), sends the question plus those candidate files over ssh to clef on
the clef machine (one clef process at a time, same lock as the text judge), asks clef a yes/no per item, and the temp
dir on the clef machine is deleted when the call ends. Videos are cut into small frames here (ffmpeg) before sending.
Clef does not read audio, and cut-off text in media is not reliable: both are stated in the output.
Never connects the private vaults (profile, documents). Env: SUPERJEV_STATE_DIR, SUPERJEV_PRINCIPAL.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import clef_client  # noqa: E402

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov"}
PRIVATE = [os.path.expanduser(p) for p in os.environ.get("SUPERJEV_PRIVATE_DIRS", "").split(os.pathsep) if p]
TOP = 4            # cap of items sent to clef per question
FRAMES = 96        # frames per clip (evenly spaced, 224 px): clef samples about one in twelve of them
MAX_ITEM_BYTES = 8_000_000
YES_AT = 0.7       # a yes below this is only a possible
MARK = clef_client.MARK
STOP = set("a an the of in on is are was what which where who when how does do did show shows image images picture photo video clip "
           "with and or to for that this it there any has have contains contain me my find".split())

_PY = (
    "import json,sys,time,io,base64\n"
    "import numpy as np\n"
    "from PIL import Image\n"
    "sys.path.insert(0,'model4')\n"
    "import clef_mlx\n"
    "req=json.load(open(sys.argv[1]))\n"
    "t=time.time(); m=clef_mlx.load('model4'); load=round(time.time()-t,2)\n"
    "out=[]\n"
    "for it in req['items']:\n"
    "    fr=[Image.open(io.BytesIO(base64.b64decode(b))).convert('RGB') for b in it['frames']]\n"
    "    rec={'state':'Look at the attached '+it['kind']+'.','questions':{'q':{'type':'noul','instructions':req['question']}}}\n"
    "    if it['kind']=='video': rec['videos']=[np.stack([np.asarray(f) for f in fr])]\n"
    "    else: rec['images']=[fr[0]]\n"
    "    t=time.time(); p=m.predict(rec)['q']; dt=round(time.time()-t,2)\n"
    "    y=p.get('true',p.get(True,0.0))\n"
    "    out.append({'id':it['id'],'p_yes':float(y),'secs':dt})\n"
    "print('" + MARK + "'+json.dumps({'results':out,'load':load}))\n"
)


def _run(body, timeout):
    sh = clef_client._SH % {"wait": clef_client.LOCK_WAIT_SECS, "dir": clef_client.REMOTE_DIR, "py": shlex.quote(_PY)}
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
           clef_client.host(), f"sh -c {shlex.quote(sh)}"]
    r = subprocess.run(cmd, input=body, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace"), r.returncode


transport = _run  # tests replace this


def state_file():
    base = os.environ.get("SUPERJEV_STATE_DIR") or os.path.expanduser("~/.local/state/super-clef")
    d = os.path.join(base, os.environ.get("SUPERJEV_PRINCIPAL", "primary"))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "media.json")


def load():
    try:
        return json.load(open(state_file()))
    except (OSError, ValueError):
        return {}


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1}


def kind_of(path):
    e = os.path.splitext(path)[1].lower()
    return "image" if e in IMAGE_EXT else "video" if e in VIDEO_EXT else None


def _private(path):
    p = os.path.realpath(path)
    return any(p == v or p.startswith(v + os.sep) for v in map(os.path.realpath, PRIVATE))


def hint(path):
    base = os.path.splitext(path)[0]
    hw = words(os.path.basename(base).replace("_", " ").replace("-", " ")) | words(os.path.basename(os.path.dirname(path)).replace("_", " ").replace("-", " "))
    for ext in (".txt", ".md"):
        try:
            hw |= words(open(base + ext, errors="replace").read(400))
        except OSError:
            pass
    return sorted(hw)


def connect(paths):
    reg, added = load(), []
    for top in paths:
        top = os.path.abspath(os.path.expanduser(top))
        if _private(top):
            print(f"refused (private vault): {top}", file=sys.stderr)
            continue
        found = [top] if os.path.isfile(top) else [os.path.join(r, f) for r, _, fs in os.walk(top) for f in fs]
        for p in sorted(found):
            if kind_of(p) and not _private(p) and os.path.isfile(p):
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                reg[p] = {"kind": kind_of(p), "sha256": h, "size": os.path.getsize(p), "hint": hint(p), "mtime": os.path.getmtime(p)}
                added.append(p)
    json.dump(reg, open(state_file(), "w"), indent=1)
    return added


def candidates(question, reg, top=TOP):
    qw = words(question)
    live = [(p, m) for p, m in reg.items() if os.path.isfile(p)]
    scored = sorted(live, key=lambda pm: (-len(qw & set(pm[1]["hint"])), -pm[1]["mtime"]))
    return scored[:top]


def frames_of(path, kind):
    """Base64 PNG/JPEG frames: the image itself, or FRAMES small frames cut from the clip with ffmpeg."""
    if kind == "image":
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im.thumbnail((896, 896))
        import io
        b = io.BytesIO()
        im.save(b, "PNG")
        return [base64.b64encode(b.getvalue()).decode()]
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is needed to read video files")
    with tempfile.TemporaryDirectory() as d:
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout.strip()
        rate = FRAMES / max(float(dur or 1), 0.5)
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={rate:.4f},scale=224:224", "-frames:v", str(FRAMES),
                            os.path.join(d, "f%04d.jpg")], capture_output=True)
        names = sorted(os.listdir(d))
        if r.returncode or not names:
            raise RuntimeError("could not read frames from the video")
        return [base64.b64encode(open(os.path.join(d, n), "rb").read()).decode() for n in names]


def ask(question, top=TOP, timeout=600):
    from prepare_bulk import payload_has_secret
    if payload_has_secret(question):
        return {"outcome": "error", "error": "the question contains a secret; not sent", "items": []}
    reg = load()
    cands = candidates(question, reg, top)
    if not cands:
        return {"outcome": "not-found", "note": "no image or video is connected", "items": []}
    items, skipped = [], []
    for p, m in cands:
        if m["size"] > MAX_ITEM_BYTES:
            skipped.append(p)
            continue
        try:
            items.append({"id": p, "kind": m["kind"], "frames": frames_of(p, m["kind"])})
        except Exception as e:  # noqa: BLE001 -- one unreadable file must not hide the rest
            skipped.append(f"{p} ({e})")
    instr = f"Does this show what the following request asks for? Request: {question}"
    body = json.dumps({"question": instr, "items": items}).encode()
    t0 = time.monotonic()
    try:
        out, err, code = transport(body, max(timeout, clef_client.LOCK_WAIT_SECS + 120))
    except subprocess.TimeoutExpired:
        return {"outcome": "error", "error": "clef on the clef machine did not answer in time", "items": []}
    line = next((ln for ln in out.splitlines() if ln.startswith(MARK)), None)
    if line is None:
        why = (err.strip().splitlines() or [""])[-1][:160]
        return {"outcome": "error", "error": f"no clef reply (exit {code}): {why}", "items": []}
    data = json.loads(line[len(MARK):])
    res = sorted(data["results"], key=lambda r: -r["p_yes"])
    shown = [{"path": r["id"], "kind": reg[r["id"]]["kind"], "p_yes": round(r["p_yes"], 3), "secs": r["secs"],
              "label": "confirmed-by-clef" if r["p_yes"] >= YES_AT else "possible" if r["p_yes"] >= 0.5 else "no"} for r in res]
    hits = [s for s in shown if s["label"] != "no"]
    return {"outcome": "found" if hits else "not-found", "items": hits, "checked": len(shown), "skipped": skipped,
            "secs": round(time.monotonic() - t0, 1), "load_secs": data.get("load"),
            "note": "clef reads no audio and cut-off text in media is not reliable"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="superclef media")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("connect"); c.add_argument("paths", nargs="+")
    sub.add_parser("list")
    a = sub.add_parser("ask"); a.add_argument("question"); a.add_argument("--top", type=int, default=TOP); a.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if ns.cmd == "connect":
        added = connect(ns.paths)
        print(f"connected {len(added)} image/video file(s) (pointers only: sha, size, hint words)")
        return 0 if added else 1
    if ns.cmd == "list":
        for p, m in sorted(load().items()):
            print(f"{m['kind']:5} {m['size']:>9} {m['sha256'][:10]} {p}")
        return 0
    r = ask(ns.question, ns.top)
    if ns.json:
        print(json.dumps(r))
    elif r["outcome"] == "found":
        print("Found (clef looked at the media itself):")
        for i, s in enumerate(r["items"], 1):
            print(f"  {i}. [{s['label']}] {s['path']}  p={s['p_yes']}")
        print(f"  checked {r['checked']} item(s) in {r['secs']}s. {r['note']}.")
    elif r["outcome"] == "not-found":
        print(f"Not found: clef checked {r.get('checked', 0)} candidate(s) and none matches. {r.get('note', '')}")
    else:
        print(f"Couldn't check: {r['error']}", file=sys.stderr)
    return 0 if r["outcome"] in ("found", "not-found") else 1


if __name__ == "__main__":
    sys.exit(main())
