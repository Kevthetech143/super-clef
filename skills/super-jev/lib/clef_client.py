#!/usr/bin/env python3
"""clef_client.py -- the clef implementation behind the judge doorway (skills/super-jev/judges).

The judge is Cloudflare clef-flash (Apache-2.0), 4-bit, run-and-exit on the clef machine. The request is the
same Jev-shape body (state + typed questions) every other judge gets; the reply is the same shape
(answers with choice and probabilities, usage), so nothing downstream knows which judge answered.

How a call goes: the body is piped over `ssh <host>`, written to a temp file on the clef machine, run through
~/clef-test (.venv/bin/python, clef_mlx), and the temp dir is deleted by a trap whether the call worked or
not. Nothing is left on the clef machine. Only one clef process may run on the clef machine at a time (12 GB peak), so the
remote side takes a lock directory first and waits for it. No key, no token, no secret is involved.

The size rule (harness REPORT 2026-10-03): the prefill runs at about 96 tokens/s, so one call is kept to a
short package (about 630 tokens). The caller shapes the package; this door refuses one over the profile's
window (TooBig) and never truncates it.

Warm path (default): a small daemon on the clef machine (lib/clefd.py) loads clef-flash once and serves calls over a
unix socket in the user's 0700 ~/.clefd, reached through one persistent ssh ControlMaster connection. It is
started on first need (its source is piped over ssh, nothing is copied to the clef machine), exits after an idle
timeout (SUPERJEV_CLEF_IDLE, default 7200 s = 2 h) and frees the model. Each call still writes its payload to a
mktemp dir that a trap removes. If the daemon cannot start or answer, the call stops it and falls back to the
one-shot path above, so a warm failure costs time, never a verdict.

Env: SUPERJEV_CLEF_HOST (required, the ssh target, e.g. user@clef-host), SUPERJEV_CLEF_DIR (default ~/clef-test on that machine),
SUPERJEV_CLEF_WARM (default 1; 0 = always one-shot), SUPERJEV_CLEF_IDLE (default 7200; the resident model is about 4.6 GB).
"""
import json
import os
import shlex
import stat
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import superclef_env  # noqa: E402,F401  (SUPERCLEF_* -> SUPERJEV_*, so this file works run directly)
from judge_profile import PROFILE, judge_tokens as estimate_tokens  # noqa: E402
from judges.errors import BadReply, TooBig, Unreachable, SecretBlocked  # noqa: E402



def host():
    """The ssh target of the judge machine. Required: there is no default."""
    h = os.environ.get("SUPERJEV_CLEF_HOST", "").strip()
    if not h:
        raise Unreachable("SUPERCLEF_CLEF_HOST is not set: set it to the ssh target of the machine that runs clef, e.g. user@clef-host")
    return h


REMOTE_DIR = os.environ.get("SUPERJEV_CLEF_DIR", "~/clef-test")
MARK = "CLEFJSON:"
LOCK_WAIT_SECS = 240
WARM = os.environ.get("SUPERJEV_CLEF_WARM", "1") != "0"
DEFAULT_IDLE_SECS = 7200  # a cold start costs about 4.5 s; the warm daemon holds about 4.6 GB on the clef machine


def _idle_secs(raw):
    """The daemon idle window in seconds: the setting when it is a whole number of at least 60, else the default."""
    try:
        n = int(str(raw).strip())
    except ValueError:
        return DEFAULT_IDLE_SECS
    return n if n >= 60 else DEFAULT_IDLE_SECS


IDLE_SECS = _idle_secs(os.environ.get("SUPERJEV_CLEF_IDLE", ""))
NO_DAEMON = 78  # exit code of the warm call when nothing is listening

# Runs on the clef machine under the lock. stdin is the request body; it is read once into a temp file that the
# trap removes. Prints one line: CLEFJSON:<reply>.
_PY = (
    "import json,sys,time\n"
    "sys.path.insert(0,'model4')\n"
    "import clef_mlx\n"
    "req=json.load(open(sys.argv[1]))\n"
    "t=time.time()\n"
    "m=clef_mlx.load('model4')\n"
    "t1=time.time()\n"
    "r=m.systemone(req)\n"
    "r['_secs']={'load':round(t1-t,2),'judge':round(time.time()-t1,2)}\n"
    "print('" + MARK + "'+json.dumps(r))\n"
)

_SH = """set -u
D=$(mktemp -d "$HOME/.clefcall.XXXXXX") || exit 70
LOCK="$HOME/.clefcall.lock"
cleanup() { rm -rf "$D"; if [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ]; then rm -rf "$LOCK"; fi; }
trap cleanup EXIT
trap 'exit 143' HUP INT TERM
cat > "$D/req.json"
i=0
while ! mkdir "$LOCK" 2>/dev/null; do
  p=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$p" ] && ! kill -0 "$p" 2>/dev/null; then rm -rf "$LOCK"; continue; fi
  i=$((i+1)); [ "$i" -gt %(wait)d ] && { echo "clef busy" >&2; exit 75; }
  sleep 1
done
echo $$ > "$LOCK/pid"
cd %(dir)s || exit 71
%(dir)s/.venv/bin/python -c %(py)s "$D/req.json"
"""


def _remote_command():
    script = _SH % {"wait": LOCK_WAIT_SECS, "dir": REMOTE_DIR, "py": shlex.quote(_PY)}
    return f"sh -c {shlex.quote(script)}"


SHORT_DIR = None  # tests point this at a temp folder
SOCKET_LIMIT = 100  # sun_path is ~104 bytes; ssh adds a random suffix while it binds, so stay under with room


def _control_dir(base=None, short=None):
    """Where the ssh ControlPath socket lives. ~/.ssh/cm-superclef-<%C hash is 40 chars>; when that would not
    fit a Unix socket path (a long HOME), use a short per-user dir under /tmp instead."""
    cm = os.path.expanduser("~/.ssh") if base is None else base
    if len(os.path.join(cm, "cm-superclef-")) + 40 + 17 > SOCKET_LIMIT:
        cm = short or SHORT_DIR or f"/tmp/scl-{os.getuid()}"
    try:
        os.makedirs(cm, mode=0o700, exist_ok=True)
        st = os.lstat(cm)  # lstat: a symlink planted at this name is not a directory here
    except OSError as e:
        raise Unreachable(f"cannot use the ssh socket folder {cm} ({e.__class__.__name__}); "
                          f"remove it or fix its owner, then retry") from None
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or (st.st_mode & 0o077):
        raise Unreachable(f"the ssh socket folder {cm} is not a private folder of yours "
                          f"(a link, someone else's, or open to others); remove it (rm -r {cm}) and retry")
    return cm


CONTROL_PERSIST = "4h"  # idle time the opening ask leaves the master up: a pause of minutes must not cost a new login
HOST_MARK = "cm-superclef-host"


def _drop_old_master(cm, target):
    """A master kept for hours must not outlive a change of host: when the host this folder last served is not
    `target`, close that host's master (ssh -O exit talks only to the local socket) and record `target`."""
    mark = os.path.join(cm, HOST_MARK)
    try:
        with open(mark) as f:
            old = f.read().strip()
    except OSError:
        old = ""
    if old == target:
        return
    if old:
        try:
            subprocess.run(["ssh", "-o", f"ControlPath={cm}/cm-superclef-%C", "-O", "exit", old],
                           capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        fd = os.open(mark, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(target)
    except OSError:
        pass


def _ssh_cmd(remote):
    cm = _control_dir()
    target = host()
    _drop_old_master(cm, target)
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ControlMaster=auto", "-o", f"ControlPath={cm}/cm-superclef-%C", "-o", f"ControlPersist={CONTROL_PERSIST}",
            target, remote]


def _exec(cmd, body, timeout):
    r = subprocess.run(cmd, input=body, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace"), r.returncode


def _run(body, timeout):
    """(stdout, stderr, code) of one remote call; the body goes in on stdin. Tests replace this."""
    return _exec(_ssh_cmd(_remote_command()), body, timeout)


# Warm call: the payload goes to a mktemp dir that a trap removes (as in the one-shot path); only its path
# goes to the daemon. Exit 78 = no daemon listening (the caller starts one).
_WARM_PY = (
    "import socket,sys,os,json\n"
    "s=socket.socket(socket.AF_UNIX)\n"
    "s.settimeout(float(sys.argv[3]))\n"
    "try: s.connect(os.path.expanduser('~/.clefd/sock'))\n"
    "except OSError: sys.exit(78)\n"
    "s.sendall((json.dumps({'req':sys.argv[1]} if sys.argv[2]=='call' else {'op':sys.argv[2]})+'\\n').encode())\n"
    "b=b''\n"
    "while not b.endswith(b'\\n'):\n"
    "    c=s.recv(65536)\n"
    "    if not c: break\n"
    "    b+=c\n"
    "print(b.decode().strip(),flush=True)\n"
    "if sys.argv[2]=='stop':\n"  # a stop returns only once the daemon has really gone (so a restart cannot race it)
    "    import time\n"
    "    for _ in range(40):\n"
    "        z=socket.socket(socket.AF_UNIX)\n"
    "        try: z.connect(os.path.expanduser('~/.clefd/sock'))\n"
    "        except OSError: break\n"
    "        z.close(); time.sleep(0.25)\n"
    "    time.sleep(0.5)\n"
)

_WARM_SH = """set -u
D=$(mktemp -d "$HOME/.clefcall.XXXXXX") || exit 70
trap 'rm -rf "$D"' EXIT
trap 'exit 143' HUP INT TERM
cat > "$D/req.json"
%(py)s -c %(code)s "$D/req.json" %(op)s %(t)d
"""


def _warm_command(op="call", timeout=120, py=None):
    py = py or f"{REMOTE_DIR}/.venv/bin/python"
    script = _WARM_SH % {"py": py, "code": shlex.quote(_WARM_PY), "op": op, "t": timeout}
    return f"sh -c {shlex.quote(script)}"


def _warm_run(body, timeout):
    return _exec(_ssh_cmd(_warm_command("call", timeout)), body, timeout + 15)


def _stop_run():
    return _exec(_ssh_cmd(_warm_command("stop", 10)), b"{}", 30)


def _daemon_source():
    return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "clefd.py"), "rb").read()


_START_SH = """set -u
D=$(mktemp -d "$HOME/.clefcall.XXXXXX") || exit 70
trap 'rm -rf "$D"' EXIT
cat > "$D/clefd.py"
cd %(dir)s || exit 71
nohup .venv/bin/python "$D/clefd.py" --idle %(idle)d --unlink-self "$D/clefd.py" >"$D/out" 2>&1 </dev/null &
i=0
while [ "$i" -lt %(wait)d ]; do
  if grep -q '^CLEFD:' "$D/out" 2>/dev/null; then grep -m1 '^CLEFD:' "$D/out"; exit 0; fi
  kill -0 $! 2>/dev/null || { echo "CLEFD:ERR daemon exited"; exit 1; }
  i=$((i+1)); sleep 1
done
echo "CLEFD:ERR start timed out"; exit 1
"""


def _start_run():
    """Start the daemon on the clef machine: its source goes in on stdin and is deleted by the daemon at once."""
    script = _START_SH % {"dir": REMOTE_DIR, "idle": IDLE_SECS, "wait": 120}
    return _exec(_ssh_cmd(f"sh -c {shlex.quote(script)}"), _daemon_source(), 180)


# Tests replace this with a fake; production runs the clef machine.
transport = _run
warm_transport = _warm_run
start_transport = _start_run
stop_transport = _stop_run


def _has_reply(out):
    return any(ln.startswith(MARK) for ln in out.splitlines())


def _warm_call(body, timeout):
    """(out, err, code) from the warm daemon, starting it on first need; None if it cannot serve this call
    (the daemon is then stopped so the one-shot path never runs beside a second loaded model)."""
    try:
        out, err, code = warm_transport(body, timeout)
        if code == NO_DAEMON:
            s_out, _, _ = start_transport()
            if "CLEFD:READY" in s_out or "CLEFD:ALREADY" in s_out:
                out, err, code = warm_transport(body, timeout)
        if _has_reply(out):
            return out, err, code
    except (subprocess.TimeoutExpired, OSError):
        pass
    try:
        stop_transport()
    except Exception:
        pass
    return None


def ask(state, questions, timeout=120):
    """One clef call for every question: {answers, model, chunks, input_tokens, latency_ms, ...}.
    Every failure is a typed judges.errors error: no verdict, never a pass."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from prepare_bulk import payload_has_secret
    if payload_has_secret(state) or payload_has_secret(questions):
        raise SecretBlocked("the request contains a secret; not sent")
    longest = max((estimate_tokens(q) for q in questions.values()), default=0)
    if estimate_tokens(state) + longest > PROFILE.call_tokens:
        raise TooBig(f"the package is over clef's short-call budget ({PROFILE.call_tokens} tokens): "
                     "it is never truncated here; the caller shortens the passages")
    body = json.dumps({"model": PROFILE.model, "state": state, "questions": questions}).encode()
    t0 = time.monotonic()
    warm = None
    try:
        warm = _warm_call(body, max(timeout, 120)) if WARM else None
        out, err, code = warm if warm else transport(body, max(timeout, LOCK_WAIT_SECS + 120))
    except subprocess.TimeoutExpired:
        raise Unreachable("clef on the clef machine did not answer in time") from None
    except OSError as e:
        raise Unreachable(f"could not run ssh: {e.__class__.__name__}") from None
    line = next((ln for ln in out.splitlines() if ln.startswith(MARK)), None)
    if line is None:
        why = (err.strip().splitlines() or [""])[-1][:160]
        if code in (255, 75) or "ssh:" in err or "Connection" in err:
            raise Unreachable(f"could not reach clef on the clef machine (exit {code}): {why}")
        raise BadReply(f"clef gave no reply (exit {code}): {why}")
    try:
        data = json.loads(line[len(MARK):])
    except ValueError:
        raise BadReply("clef reply was not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise BadReply("clef reply had no answers")
    usage = data.get("usage") or {}
    return {"answers": data["answers"], "model": data.get("model") or PROFILE.model, "chunks": 1,
            "input_tokens": usage.get("input_tokens", 0),
            "latency_ms": round((time.monotonic() - t0) * 1000), "secs": data.get("_secs"), "warm": bool(warm)}


def main(argv=None):
    """The gate's door under clef: same claim-check CLI and table as jev_client, whose check() asks
    through judges.ask (so it lands in ask() above). Every failure is a typed error: exit 1, no verdict."""
    import jev_client
    return jev_client.main(argv)


if __name__ == "__main__":
    sys.exit(main())
