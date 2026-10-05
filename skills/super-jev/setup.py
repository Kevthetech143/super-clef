#!/usr/bin/env python3
"""One-command setup (and uninstall) for Super Jev.

    python3 skills/super-jev/setup.py              # set up; safe to run again
    python3 skills/super-jev/setup.py --uninstall  # remove everything setup and connect created

Setup creates the state folder ($SUPERJEV_STATE_DIR, default
~/.local/state/super-clef) with owner-only permissions and a memory config
inside it, checks Node, Python and the TypeSafe key, and prints the next
step. For anything missing it prints the exact steps to get it, none needing
admin rights (the docs repeat those lines word for word; a test keeps them
identical). It never overwrites an existing config and never reads or prints
the key's value.

This file and what it imports (judges/, judge_profile.py) must stay runnable on
Python 3.9, the interpreter a stock Mac has, because it is the one door that
tells that Mac how to get Python 3.10 or newer.

Uninstall removes what Super Jev wrote: the state folder (connected pointers,
cached answers, logs, manual records, and its prepare-cache/ inside it), the old in-tree
prepare-cache/, ledger/ and autoheal-state/ folders of this skill, the chat CLI's config (it holds your API key) and its
launcher if install.sh made it for this checkout, and any ~/.claude/skills links
that point into this checkout. One rule: in each of those folders it deletes the
names it writes (the OWNED table below) and keeps everything else. Your original
files are never touched.
"""
import fnmatch
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
REPO = SKILL_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))
import superclef_env  # noqa: E402,F401  (SUPERCLEF_* -> SUPERJEV_*, before anything reads env)
import judges  # noqa: E402
# prepare_bulk.py lists every file it writes into prepare-cache/ here.
WRITTEN_MANIFEST = ".superjev-written"
# In-repo folders Super Jev writes to. Uninstall deletes only files it can prove it
# wrote (see _ours_in); anything else is left in place.
IN_REPO_LEFTOVERS = (SKILL_DIR / "prepare-cache", SKILL_DIR / "ledger", SKILL_DIR / "autoheal-state")
# Every name Super Jev writes, folder by folder (fnmatch patterns, matched on the name only). Uninstall
# deletes a match and keeps everything else; a folder goes once it is empty. "principal" is each
# <state>/<principal>/ folder. tests/test_uninstall_complete.py scans the writers and fails when a
# name they build is missing here, so add a new writer's name below.
OWNED = {
    "principal": ("lookups.jsonl", "traces.jsonl", "traces.jsonl.1", "approvals.jsonl", "claim-verdicts.json",
                  "pointer_health.json", "pointer-words.json", "pointer-words.*.tmp", "toc-cache.json", "toc-cache.json.tmp*", "stat-sha.sqlite", "stat-sha.sqlite-journal",
                  "scorecard-cases.jsonl", "scorecard-cases.tmp", "manual", "github"),
    "ledger": ("calls.jsonl", "catches.jsonl", "catches.jsonl.lock", "catches.jsonl.tmp", "catch-cases.json",
               "catch-cases.json.tmp", "signals.jsonl", "payloads", "state", "last", "calibration"),
    "autoheal-state": ("autoheal.log", "*.json", ".*.json.*", ".*.state-lock", ".*.lock-control", "*.lock",
                       ".*.lock.tmp.*", "*-last-refresh.log"),
}
# install.sh writes the chat launcher with this marker line and an exec of its checkout
LAUNCHER_MARKER = "# super-jev-installer"
CLEF_LAUNCHER_MARKER = "# super-clef-installer"

MIN_NODE = 24
MIN_PYTHON = (3, 10)
# The exact lines for a machine that lacks one. No admin rights needed: uv and nvm install into
# the home folder. AGENTS.md and docs/GETTING-STARTED.md repeat these lines word for word
# (install.sh repeats the node ones); tests/test_setup_toolchain.py keeps them identical.
INSTALL = {
    "python": ('curl -LsSf https://astral.sh/uv/install.sh | sh',
               'source "$HOME/.local/bin/env"',
               'uv python install 3.12 --default'),
    # nvm keeps itself on PATH only by editing a shell startup file that already exists
    "node_zsh": ('touch ~/.zshrc',),
    "node": ('curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh | bash',
             '\\. "$HOME/.nvm/nvm.sh"',
             'nvm install 24'),
}
HOMEBREW = "Already use Homebrew? Run: brew install node python"


def state_root() -> Path:
    root = os.environ.get("SUPERJEV_STATE_DIR")
    return Path(root).expanduser() if root else Path.home() / ".local/state/super-clef"


def config_path() -> Path:
    return state_root() / "_memory" / "config.json"


def _node_major():
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError):
        return None


def _python_version():
    return tuple(sys.version_info[:3])


def _judge_reachable(host: str) -> bool:
    """True when ssh key login to the judge machine works (no prompt, 8 second limit)."""
    try:
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "true"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _only_connect_wrote(root: Path) -> bool:
    """True when root is empty, or holds only what `superclef connect` writes: _memory/registry.json,
    prepare-cache/, and per-principal folders of the names in OWNED."""
    for f in root.iterdir():
        if f.is_symlink() or not f.is_dir():
            return False
        if f.name == "_memory":
            ok = all(g.name == "registry.json" and g.is_file() for g in f.iterdir())
        elif f.name == "prepare-cache":
            ok = True
        else:
            ok = all(_owned(g.name, "principal") for g in f.iterdir())
        if not ok:
            return False
    return True


def _block(*lines) -> str:
    return "".join("\n        " + ln for ln in lines)


def setup() -> int:
    problems = []
    steps = False   # an install block was printed, so say how to pick it up in this shell
    python = _python_version()
    if python < MIN_PYTHON:
        problems.append("Python %d.%d or newer is required (found: %s). Install it with uv (into your home folder, no admin rights needed):%s"
                        % (MIN_PYTHON + (".".join(map(str, python)), _block(*INSTALL["python"]))))
        steps = True
    node = _node_major()
    if node is None or node < MIN_NODE:
        zsh = "zsh" in os.environ.get("SHELL", "")
        problems.append("Node %d or newer is required (found: %s). Install it with nvm (into your home folder, no admin rights needed):%s"
                        % (MIN_NODE, "none" if node is None else f"v{node}",
                           _block(*(INSTALL["node_zsh"] if zsh else ()), *INSTALL["node"])))
        steps = True

    cfg = config_path()
    root = state_root()
    if root.exists() and not cfg.is_file() and (not root.is_dir() or not _only_connect_wrote(root)):
        # A folder setup did not make, with something already in it, may be the user's own
        # files; planting a config there would later let --uninstall claim it. A folder holding
        # only what `superclef connect` wrote (its registry or prepare-cache) is ours.
        print(f"REFUSED: {root} already exists and is not empty, and setup did not make it. "
              "Point SUPERCLEF_STATE_DIR at a new or empty folder, then run setup again.")
        return 1
    cfg.parent.mkdir(parents=True, exist_ok=True)
    for d in (state_root(), cfg.parent):
        os.chmod(d, 0o700)
    if cfg.is_file():
        print(f"ok    memory config already exists: {cfg} (left unchanged)")
    else:
        cfg.write_text(json.dumps({"db": "memory.sqlite3", "registry": "registry.json"},
                                  indent=2) + "\n")
        os.chmod(cfg, 0o600)
        print(f"made  memory config: {cfg}")
    print(f"ok    state folder: {state_root()}")
    roots = state_root() / "skill-roots.json"   # extra skill folders for the skill finder; empty is fine
    if not roots.exists():
        roots.write_text("[]\n")
        os.chmod(roots, 0o600)
        print(f"made  skill roots list: {roots} (empty; add folders to search more skills)")

    key_env = judges.key_env()
    if judges.key_present():
        if key_env:
            print(f"ok    {key_env} is set")
    else:
        where = judges.key_file()
        lines = [f'export {key_env}="$(cat {where})"']
        note = ""
        if not Path(where).expanduser().exists():   # existence only: setup never opens the key file
            lines.insert(0, f"(umask 077; cat > {where})")
            note = (" Make the key file first: run the first line, paste the key, press Enter, then Ctrl-D"
                    " (your human does this in their own terminal; never paste a key into chat)."
                    " Then load it:")
        problems.append(f"{key_env} is not set. Every ask and check needs it.{note or ' Run:'}"
                        + _block(*lines))

    if judges.profile().kind == "clef":
        host = os.environ.get("SUPERJEV_CLEF_HOST", "").strip()
        how = ("Set the judge host to the ssh target of the machine that runs clef, with key login, and run setup again:"
               "\n        export SUPERCLEF_CLEF_HOST=user@clef-host")
        if not host:
            problems.append("The judge host is not set. " + how)
        elif _judge_reachable(host):
            print(f"ok    judge machine reachable over ssh: {host}")
        else:
            problems.append(f"The judge machine {host} did not answer ssh (ssh -o BatchMode=yes -o ConnectTimeout=8 {host} true failed). "
                            "Check the name and that key login works, or " + how[0].lower() + how[1:])

    if shutil.which("claude"):
        print("ok    description writer: claude CLI found (connect uses it only if it is logged in; "
              "--writer builtin needs no login)")
    else:
        print("ok    description writer: no claude CLI, so connect uses the built-in writer "
              "(no extra login needed)")

    if problems:
        print("\nNOT READY:")
        for p in problems:
            print("  - " + p)
        if steps:
            print("\n  " + HOMEBREW)
            print("\nRun the source lines above in this shell, or open a new terminal, then run setup again.")
        else:
            print("\nFix the above, then run setup again.")
        return 1
    print("\nREADY. Next step: connect a folder of .md files:\n"
          "  superclef connect /path/to/folder")
    return 0


def _links_into_repo():
    skills = Path.home() / ".claude" / "skills"
    if not skills.is_dir():
        return []
    out = []
    for p in skills.iterdir():
        if p.is_symlink():
            try:
                target = p.resolve()
            except OSError:
                continue
            if target == REPO or REPO in target.parents:
                out.append(p)
    return out


def _registered_pointers() -> list:
    try:
        return list(json.loads((state_root() / "_memory" / "registry.json").read_text())["datasets"])
    except Exception:
        return []


def _owned(name: str, folder: str) -> bool:
    """True when `name` is one Super Jev writes in a folder of this kind (see OWNED)."""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in OWNED.get(folder, ()))


def _ours_in(d: Path) -> set:
    """Files in d Super Jev can prove it wrote: the names in OWNED for this folder, names listed
    in d's manifest, and names derived from registered pointers (installs from before the manifest)."""
    ours = {f for f in d.iterdir() if _owned(f.name, d.name)}
    m = d / WRITTEN_MANIFEST
    if m.is_file() and not m.is_symlink():
        ours |= {d / n for n in m.read_text().split("\n") if n and "/" not in n and n not in (".", "..")}
        ours.add(m)
    for p in _registered_pointers():
        ours |= {d / f"{p}.json", d / f"{p}-held.txt", d / f"{p}-report.json"}
        ours |= {f for f in d.glob(f"{glob.escape(p)}-*.json") if re.fullmatch(rf"{re.escape(p)}-\d+\.json", f.name)}
    return ours


def _clear(d: Path, folder: str, removed: list, kept: list) -> None:
    """Delete the names Super Jev writes in d (OWNED[folder]); add what stays to `kept`; remove d once empty."""
    left = []
    for f in sorted(d.iterdir()):
        if _owned(f.name, folder) and not f.is_symlink():
            shutil.rmtree(f) if f.is_dir() else f.unlink()
            removed.append(str(f))
        else:
            left.append(str(f))
    kept.extend(left)
    if not left:
        d.rmdir()
        removed.append(str(d))


def _remove_chat_cli(removed: list, kept: list) -> None:
    """The chat CLI's config (it holds an API key) and the launcher install.sh wrote. The folders
    are the ones src/jev-chat-config.ts and install.sh use. The launcher goes only when it carries
    install.sh's marker line and execs THIS checkout's chat CLI."""
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "superjev"
    config = config_dir / "config.json"
    if config_dir.is_dir() and not config_dir.is_symlink() and config.is_file() and not config.is_symlink():
        config.unlink()
        removed.append(str(config))
        if any(config_dir.iterdir()):
            kept.extend(str(f) for f in sorted(config_dir.iterdir()))
        else:
            config_dir.rmdir()
            removed.append(str(config_dir))
    bin_dir = Path(os.environ.get("SUPERJEV_BIN_DIR") or Path.home() / ".local/bin")
    # The old `superjev` launcher (old marker, jev-chat-cli.ts) and the current `superclef` one
    # (scripts/install-superclef.sh). Each goes only with its own marker line and an exec of this checkout.
    for name, marker, entry in (("superjev", LAUNCHER_MARKER, r"/src/jev-chat-cli\.ts"),
                                ("superclef", CLEF_LAUNCHER_MARKER, r"/bin/superclef\.js")):
        launcher = bin_dir / name
        if not (launcher.is_file() and not launcher.is_symlink() and launcher.stat().st_size < 4096):
            continue
        lines = launcher.read_text(errors="replace").splitlines()
        execs = [m.group(1) for m in (re.fullmatch(r'exec node "(.+)' + entry + r'" "\$@"', ln) for ln in lines) if m]
        if any(ln == marker or ln.startswith(marker + ":") for ln in lines) and any(Path(e).resolve() == REPO for e in execs):
            launcher.unlink()
            removed.append(str(launcher))


def _is_empty_list(f: Path) -> bool:
    try:
        return json.loads(f.read_text()) == []
    except Exception:
        return False


def _sweep_cache(d: Path, removed: list, kept: list) -> None:
    """The state dir's prepare-cache: same rule as the in-tree one (_ours_in); the rest stays."""
    ours = _ours_in(d)
    for f in sorted(d.iterdir()):
        if f.is_file() and not f.is_symlink() and f in ours:
            f.unlink()
            removed.append(str(f))
        elif (f.name == "growth" and f.is_dir() and not f.is_symlink() and f in ours
              and all(g.is_file() and not g.is_symlink() and ".json" in g.name for g in f.iterdir())):
            shutil.rmtree(f)
            removed.append(str(f))
        else:
            kept.append(str(f))
    if any(d.iterdir()):
        return
    d.rmdir()
    removed.append(str(d))


def uninstall() -> int:
    removed = []
    root = state_root()
    if root.exists() and not config_path().is_file():
        # Only a folder setup made (it holds setup's _memory/config.json) is ours to
        # delete; SUPERJEV_STATE_DIR may point at a folder of the user's own files.
        print(f"REFUSED: {root} has no {config_path().relative_to(root)} (the marker setup "
              "writes), so it may not be a Super Clef state folder. Nothing was deleted; "
              "check SUPERCLEF_STATE_DIR, or delete that folder yourself if it is Super Clef's.")
        return 1
    kept, repo_kept = [], []
    for d in IN_REPO_LEFTOVERS:
        if not d.is_dir() or d.is_symlink():
            continue
        ours = _ours_in(d)
        for f in sorted(d.iterdir()):
            if f.is_file() and not f.is_symlink() and f in ours:
                f.unlink()
                removed.append(str(f))
            elif (f.name == "growth" and f in ours and f.is_dir() and not f.is_symlink()
                  and all(g.is_file() and not g.is_symlink() and ".json" in g.name for g in f.iterdir())):
                # prepare_bulk's new-file snapshots (one <pointer>.json each; they name file paths)
                shutil.rmtree(f)
                removed.append(str(f))
            elif f.is_dir() and not f.is_symlink() and _owned(f.name, d.name):
                shutil.rmtree(f)  # a folder Super Jev writes (ledger/payloads/, ledger/state/ ...)
                removed.append(str(f))
            else:
                repo_kept.append(str(f))
        if not any(d.iterdir()):
            d.rmdir()
            removed.append(str(d))
    if root.is_dir():
        # _memory/ is setup's. In each other folder (one per principal) delete the names Super Jev
        # writes there (OWNED) and keep the rest; a folder goes once it is empty, and so does the
        # state folder.
        for child in sorted(root.iterdir()):
            if child.name == "_memory":
                shutil.rmtree(child)
                removed.append(str(child))
            elif child.name == "prepare-cache" and child.is_dir() and not child.is_symlink():
                _sweep_cache(child, removed, kept)
            elif child.name == "skill-roots.json" and child.is_file() and _is_empty_list(child):
                child.unlink()   # setup's empty list; a list the user filled stays
                removed.append(str(child))
            elif child.is_dir() and not child.is_symlink():
                _clear(child, "principal", removed, kept)
            else:
                kept.append(str(child))
        if not kept:
            root.rmdir()
            removed.append(str(root))
    _remove_chat_cli(removed, repo_kept)
    for link in _links_into_repo():
        link.unlink()
        removed.append(str(link))
    # empty parents setup made (~/.local/state, ~/.local); never a folder with anything in it
    if not os.environ.get("SUPERJEV_STATE_DIR"):
        for parent in (Path.home() / ".local/state", Path.home() / ".local"):
            if not parent.is_dir() or any(parent.iterdir()):
                break
            parent.rmdir()
            removed.append(str(parent))
    for sub in ("skills", "experiments"):
        for cache in (REPO / sub).rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
    if removed:
        print("removed:\n  " + "\n  ".join(removed))
    if repo_kept:
        print("left in place (not made by Super Clef):\n  " + "\n  ".join(repo_kept))
    if kept:
        print(f"left in place (not made by Super Clef), so {root} was kept:\n  " + "\n  ".join(kept))
    print("Super Clef is uninstalled. Your original files were not touched. "
          "Delete this checkout folder to remove the code too.")
    return 0


def main(argv) -> int:
    if argv == ["--uninstall"]:
        return uninstall()
    if argv:
        print(__doc__)
        return 2
    return setup()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
