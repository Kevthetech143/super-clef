#!/usr/bin/env python3
"""clefd.py -- the warm clef judge: runs ON THE MINI, loads clef-flash once, serves judge calls over a unix
socket in the user's own 0700 directory (nothing listens on the network), and exits after an idle timeout.

The client (clef_client.py) pipes this file's source to the clef machine over ssh; the starter shell runs it in the
background from a temp file the daemon deletes at once, so no copy of it stays there. It prints one status
line (CLEFD:READY, CLEFD:ALREADY or CLEFD:ERR <why>) that the starter relays; then it is quiet.

Guarantees: one daemon per user (flock), one model loaded, a per-call lock shared with the one-shot path
(mkdir ~/.clefcall.lock) so two judges never run at once, an idle exit that removes the socket and frees the
memory, and a request is only a path to a payload file under ~/.clefcall.* that the caller deletes.
Protocol, one line each way: {"req": "<path>"} -> CLEFJSON:<reply> | CLEFERR:<why>; {"op":"ping"}; {"op":"stop"}.
"""
import json
import os
import socket
import sys
import time

MARK = "CLEFJSON:"
ERR = "CLEFERR:"


def paths(home):
    d = os.path.join(home, ".clefd")
    return d, os.path.join(d, "sock"), os.path.join(d, "lock")


def idle_expired(last_active, now, idle_secs):
    return now - last_active >= idle_secs


def acquire_single_instance(lock_path):
    """An flock held for the life of the process; the OS drops it if the daemon dies. None if another holds it."""
    import fcntl
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


class CallLock:
    """The clef machine-wide call lock the one-shot path uses (mkdir ~/.clefcall.lock, pid inside)."""

    def __init__(self, home, wait=240):
        self.path = os.path.join(home, ".clefcall.lock")
        self.wait = wait

    def __enter__(self):
        for _ in range(self.wait):
            try:
                os.mkdir(self.path)
                with open(os.path.join(self.path, "pid"), "w") as f:
                    f.write(str(os.getpid()))
                return self
            except FileExistsError:
                try:
                    pid = int(open(os.path.join(self.path, "pid")).read().strip() or 0)
                    os.kill(pid, 0)
                except (ValueError, OSError):
                    self._rm()
                    continue
                time.sleep(1)
        raise TimeoutError("clef busy")

    def _rm(self):
        import shutil
        shutil.rmtree(self.path, ignore_errors=True)

    def __exit__(self, *a):
        self._rm()


def payload_ok(home, path):
    """Only a req.json inside a ~/.clefcall.<random> directory the caller made; nothing else is ever read."""
    real = os.path.realpath(path)
    base = os.path.realpath(home)
    rel = os.path.relpath(real, base)
    parts = rel.split(os.sep)
    return len(parts) == 2 and parts[0].startswith(".clefcall.") and parts[0] != ".clefcall.lock" and parts[1] == "req.json"


def handle(line, judge, home, lock_wait=240):
    """One request line -> (reply line, stop?). judge(req dict) -> reply dict."""
    try:
        msg = json.loads(line)
    except ValueError:
        return ERR + "bad request", False
    if msg.get("op") == "ping":
        return "CLEFD:PONG", False
    if msg.get("op") == "stop":
        return "CLEFD:STOPPING", True
    path = msg.get("req")
    if not isinstance(path, str) or not payload_ok(home, path):
        return ERR + "bad payload path", False
    try:
        with CallLock(home, lock_wait):
            req = json.load(open(path))
            t = time.time()
            r = judge(req)
            r["_secs"] = {"load": 0, "judge": round(time.time() - t, 2)}
        return MARK + json.dumps(r), False
    except Exception as e:  # a bad call must not kill the warm model
        return ERR + f"{e.__class__.__name__}: {str(e)[:160]}", False


def serve(srv, judge, home, idle_secs, clock=time.monotonic, lock_wait=240):
    """Accept loop on a listening socket. Returns when idle for idle_secs or on a stop request."""
    last = clock()
    srv.settimeout(1.0)
    while not idle_expired(last, clock(), idle_secs):
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        stop = False
        try:
            conn.settimeout(10)
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            reply, stop = handle(buf.decode("utf-8", "replace").strip(), judge, home, lock_wait)
            conn.sendall((reply + "\n").encode())
        except OSError:
            pass
        finally:
            conn.close()
        last = clock()
        if stop:
            break


def bind(sock_path):
    if os.path.exists(sock_path):
        os.unlink(sock_path)  # stale: we hold the single-instance lock, so nobody else owns it
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    os.chmod(sock_path, 0o600)
    srv.listen(8)
    return srv


def _load_model(model_dir):
    sys.path.insert(0, model_dir)
    import clef_mlx
    m = clef_mlx.load(model_dir)
    return m.systemone


def main(argv):
    idle = 600
    model_dir = "model4"
    home = os.path.expanduser("~")
    for i, a in enumerate(argv):
        if a == "--idle":
            idle = int(argv[i + 1])
        elif a == "--model":
            model_dir = argv[i + 1]
        elif a == "--home":
            home = argv[i + 1]
        elif a == "--unlink-self":  # the starter wrote this source to a temp file only so python could run it
            try:
                os.unlink(argv[i + 1])
            except OSError:
                pass
    os.umask(0o077)
    d, sock_path, lock_path = paths(home)
    os.makedirs(d, mode=0o700, exist_ok=True)

    def tell(m):
        print("CLEFD:" + m, flush=True)

    fd = None
    for _ in range(20):  # a daemon that was just told to stop may still be letting go of the lock
        fd = acquire_single_instance(lock_path)
        if fd is not None:
            break
        time.sleep(0.5)
    if fd is None:
        tell("ALREADY")
        return
    srv = None
    try:
        judge = _load_model(model_dir)
        srv = bind(sock_path)
    except Exception as e:
        tell(f"ERR {e.__class__.__name__}: {str(e)[:120]}")
        return
    tell("READY")
    try:
        serve(srv, judge, home, idle)
    finally:
        srv.close()
        for f in (sock_path, lock_path):
            try:
                os.unlink(f)
            except OSError:
                pass
        try:
            os.rmdir(d)
        except OSError:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
