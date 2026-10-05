#!/usr/bin/env python3
"""import_state.py -- `superclef import-state --from-superjev`: give Super Clef the same connected files
Super Jev has, so both search identical files.

READ-ONLY on Super Jev's side: its answer database is opened mode=ro and copied with sqlite's backup, every
other file is read and written into Super Clef's own state dir (default ~/.local/state/super-clef) and this
skill's own prepare-cache/. Nothing in Super Jev's folders is written, moved or deleted.

What is copied (the connected-set state, small and local):
  _memory/answers.sqlite    the registered pointers (which sets exist, who sees them) and saved answers
  _memory/registry.json     the dataset registry (what each pointer's reviewed files are)
  _memory/config.json       rewritten to point at the two copies above; Super Clef has no TypeSafe provider
  prepare-cache/            each set's file list (the word search reads these)
  shared-pointers.json, skill-roots.json
  <principal>/approvals.jsonl, <principal>/manual/   saved answers and manual notes, per principal

The reviewed-dataset manifests and the originals the registry names are NOT copied: the registry pins them
by absolute path and hash, so Super Clef reads them in place (read-only), and the files you connected stay
where they are. No file contents leave this Mac; the only thing that ever goes to the clef machine is the one short
package of each question (skills/super-jev/lib/clef_client.py).
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
SKIP_PRINCIPAL_PREFIXES = ("abs-", "pb-", "_memory")  # benchmark test principals: not connected files


def clef_state() -> Path:
    root = os.environ.get("SUPERJEV_STATE_DIR")
    return Path(root).expanduser() if root else HOME / ".local/state/super-clef"


def jev_state() -> Path:
    return HOME / ".local/state/super-jev"


def jev_skill_dir() -> Path:
    return (HOME / ".claude/skills/super-jev").resolve()


def live_config() -> Path:
    """The memory config Super Jev's own wrapper (memory.sh) passes with --config; else its state-dir one."""
    try:
        m = re.search(r"--config\s+(\S+)", (jev_skill_dir() / "memory.sh").read_text())
        if m and Path(m.group(1)).expanduser().is_file():
            return Path(m.group(1)).expanduser()
    except OSError:
        pass
    return jev_state() / "_memory" / "config.json"


def _copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for p in src.rglob("*"):
        if p.is_file():
            t = dst / p.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, t)
            n += 1
    return n


def _synthesize_caches(datasets: dict, cache_dir: Path) -> int:
    """Super Jev routes a split set's later parts (<set>-2, -3 ...) through its Jev navigation, so they have no
    prepare-cache file. Super Clef has no such provider: it gives each of them a file list built from the
    registry's own record of what was reviewed (path + sha256 of every original). Reviewed views (no `structure`)
    stay unsearched on purpose: they hold de-identified copies, never the raw originals."""
    made = 0
    for name, e in datasets.items():
        f = cache_dir / f"{name}.json"
        if f.exists() or not isinstance(e, dict) or not e.get("structure") or not e.get("originals"):
            continue
        files = {o["path"]: {"sha256": o["sha256"], "description": "", "kind": "unknown", "status": "unknown",
                             "as_of": "unknown", "subject": "unknown", "verdict": "SUPPORTED", "confidence": 1.0, "pass": True,
                             "from_registry": True}
                 for o in e["originals"] if isinstance(o, dict) and o.get("path") and o.get("sha256")}
        if files:
            f.write_text(json.dumps(files))
            made += 1
    return made


def run(args) -> int:
    src = Path(args.state).expanduser() if args.state else jev_state()
    dst = clef_state()
    if src.resolve() == dst.resolve():
        print("import-state: the source and Super Clef's state dir are the same folder; nothing to do", file=sys.stderr)
        return 2
    cfg_path = Path(args.config).expanduser() if args.config else live_config()
    if not cfg_path.is_file():
        print(f"import-state: no Super Jev memory config at {cfg_path} (pass --config)", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_path.read_text())
    base = cfg_path.parent
    db_src = (base / cfg["db"]).expanduser()
    reg_src = (base / cfg["registry"]).expanduser()
    for p in (db_src, reg_src):
        if not p.is_file():
            print(f"import-state: missing {p}", file=sys.stderr)
            return 2
    mem = dst / "_memory"
    mem.mkdir(parents=True, exist_ok=True)
    os.chmod(dst, 0o700)
    # the answer database: a read-only open, copied with sqlite's own backup (a consistent snapshot)
    ro = sqlite3.connect(f"file:{db_src}?mode=ro", uri=True)
    out = sqlite3.connect(mem / "answers.sqlite")
    try:
        ro.backup(out)
    finally:
        out.close()
        ro.close()
    shutil.copy2(reg_src, mem / "registry.json")
    provider = HERE / "no_provider.py"
    new_cfg = {**{k: v for k, v in cfg.items() if k not in ("db", "registry", "retrievalCommand", "navigationCommand", "_base")},
               "db": str(mem / "answers.sqlite"), "registry": str(mem / "registry.json"),
               "retrievalCommand": [sys.executable, str(provider)], "navigationCommand": [sys.executable, str(provider)]}
    (mem / "config.json").write_text(json.dumps(new_cfg, indent=2) + "\n")
    # per-set file lists, from the Super Jev skill folder
    cache_src = Path(args.skill_dir).expanduser() / "prepare-cache" if args.skill_dir else jev_skill_dir() / "prepare-cache"
    n_cache = _copy_tree(cache_src, clef_state() / "prepare-cache") if cache_src.is_dir() else 0
    n_made = _synthesize_caches(json.loads((mem / "registry.json").read_text()).get("datasets") or {}, clef_state() / "prepare-cache")
    for name in ("shared-pointers.json", "skill-roots.json"):
        if (src / name).is_file():
            shutil.copy2(src / name, dst / name)
    n_principals = 0
    for d in sorted(src.iterdir()):
        if not d.is_dir() or d.name.startswith(SKIP_PRINCIPAL_PREFIXES) or d.name.startswith("."):
            continue
        copied = False
        if (d / "approvals.jsonl").is_file():
            (dst / d.name).mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / "approvals.jsonl", dst / d.name / "approvals.jsonl")
            copied = True
        if (d / "manual").is_dir():
            _copy_tree(d / "manual", dst / d.name / "manual")
            copied = True
        n_principals += copied
    reg = json.loads((mem / "registry.json").read_text())
    n_sets = len(reg.get("datasets") or {})
    result = {"imported": True, "from": str(src), "to": str(dst), "datasets": n_sets,
              "prepare_cache_files": n_cache, "file_lists_made_from_registry": n_made, "principals": n_principals,
              "note": "reviewed manifests and the originals are read in place (read-only); nothing was written to Super Jev"}
    print(json.dumps(result) if args.json else
          f"Imported Super Jev's connected sets into {dst}: {n_sets} datasets, {n_cache} set file lists, "
          f"{n_principals} principals' saved answers. Originals stay where they are; nothing was written to Super Jev.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="superclef import-state")
    ap.add_argument("--from-superjev", action="store_true", required=True,
                    help="copy Super Jev's connected-set state (read-only) into Super Clef's own state dir")
    ap.add_argument("--config", help="Super Jev's memory config.json (default: the one its memory.sh wrapper passes)")
    ap.add_argument("--state", help="Super Jev's state dir (default ~/.local/state/super-jev)")
    ap.add_argument("--skill-dir", help="Super Jev's skill dir holding prepare-cache/ (default ~/.claude/skills/super-jev)")
    ap.add_argument("--json", action="store_true")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
