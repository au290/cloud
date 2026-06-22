#!/usr/bin/env python3
"""Single entry point — starts every service for the MiniStack storage portal.

Launches (and supervises) three processes:
  1. MiniStack   — the Docker-free AWS emulator on :4566 (S3 + IAM)
  2. Flask API   — backend/app.py (serves the API + frontend on :8000)
  3. Worker      — backend/worker.py (periodic quota reconciliation)

PostgreSQL is assumed to be already running (it's a system service); the launcher
only checks that it's reachable. Output from all services is streamed with a
coloured [prefix]. Press Ctrl+C once to stop everything cleanly.

Usage:
    python run.py                  # start all services
    python run.py --no-ministack   # skip MiniStack (e.g. running it yourself)
    python run.py --no-worker      # skip the reconciliation worker
"""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")

# ANSI colours for the per-service log prefixes (ignored on dumb terminals).
COLORS = {"ministack": "\033[35m", "api": "\033[36m", "worker": "\033[33m",
          "run": "\033[32m", "_": "\033[0m"}

_procs: list[subprocess.Popen] = []
_stopping = False


def log(name, msg):
    c = COLORS.get(name, "") if sys.stdout.isatty() else ""
    r = COLORS["_"] if sys.stdout.isatty() else ""
    print(f"{c}[{name}]{r} {msg}", flush=True)


def venv_python() -> str:
    """Prefer the project venv interpreter so the right deps are used."""
    cand = os.path.join(BACKEND, "venv", "Scripts" if os.name == "nt" else "bin",
                        "python.exe" if os.name == "nt" else "python")
    return cand if os.path.isfile(cand) else sys.executable


def load_env() -> dict:
    env = os.environ.copy()
    path = os.path.join(ROOT, ".env")
    if os.path.isfile(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    return env


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def stream(name: str, proc: subprocess.Popen):
    """Pump a child's combined stdout/stderr into our prefixed log."""
    for line in iter(proc.stdout.readline, ""):
        if line:
            log(name, line.rstrip())
    proc.stdout.close()


def start(name: str, cmd: list[str], env: dict, cwd: str = None) -> subprocess.Popen:
    log("run", f"starting {name}: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    _procs.append(proc)
    threading.Thread(target=stream, args=(name, proc), daemon=True).start()
    return proc


def check_postgres(env: dict) -> bool:
    url = env.get("DATABASE_URL", "postgresql://postgres:user@localhost:5432/iaas")
    parsed = urlparse(url)
    host, port = parsed.hostname or "localhost", parsed.port or 5432
    log("run", f"checking PostgreSQL at {host}:{port} ...")
    for _ in range(10):
        if port_open(host, port):
            log("run", "PostgreSQL is reachable.")
            return True
        time.sleep(1)
    log("run", "PostgreSQL NOT reachable — start it, then re-run. (Postgres is "
               "a prerequisite; this launcher does not start it.)")
    return False


def find_ministack() -> list[str] | None:
    exe = shutil.which("ministack")
    if exe:
        return [exe]
    scripts = os.path.join(BACKEND, "venv", "Scripts" if os.name == "nt" else "bin",
                           "ministack.exe" if os.name == "nt" else "ministack")
    if os.path.isfile(scripts):
        return [scripts]
    # Last resort: module form.
    return [venv_python(), "-m", "ministack"]


def shutdown(*_):
    global _stopping
    if _stopping:
        return
    _stopping = True
    log("run", "shutting down services ...")
    for proc in reversed(_procs):
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
    deadline = time.time() + 8
    for proc in reversed(_procs):
        try:
            proc.wait(timeout=max(0, deadline - time.time()))
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    log("run", "all services stopped.")


def main():
    ap = argparse.ArgumentParser(description="Start all MiniStack storage portal services.")
    ap.add_argument("--no-ministack", action="store_true", help="don't start MiniStack")
    ap.add_argument("--no-worker", action="store_true", help="don't start the worker")
    args = ap.parse_args()

    env = load_env()
    py = venv_python()
    api_port = int(env.get("APP_PORT", "8000"))

    if not check_postgres(env):
        sys.exit(1)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 1) MiniStack first, so the API can provision buckets/keys on startup.
    endpoint = env.get("MINISTACK_ENDPOINT", "http://localhost:4566")
    ms_port = urlparse(endpoint).port or 4566
    if not args.no_ministack:
        if port_open("localhost", ms_port):
            log("run", f"MiniStack already running on :{ms_port}, reusing it.")
        else:
            # Persist state so buckets/objects survive a MiniStack restart (skill §1).
            env.setdefault("PERSIST_STATE", "1")
            log("run", f"starting MiniStack with PERSIST_STATE={env.get('PERSIST_STATE')}")
            start("ministack", find_ministack(), env)
            log("run", f"waiting for MiniStack on :{ms_port} ...")
            for _ in range(20):
                if port_open("localhost", ms_port):
                    log("run", "MiniStack is up.")
                    break
                time.sleep(1)
            else:
                log("run", "MiniStack did not come up in time — continuing anyway "
                           "(object operations may fail until it's available).")

    # 2) Flask API.
    start("api", [py, "app.py"], env, cwd=BACKEND)

    # 3) Worker.
    if not args.no_worker:
        time.sleep(2)  # let the API create tables/seed first
        start("worker", [py, "worker.py"], env, cwd=BACKEND)

    log("run", f"Portal: http://localhost:{api_port}  (Ctrl+C to stop)")

    # Supervise: if any service dies, tear the rest down.
    try:
        while not _stopping:
            for proc in list(_procs):
                code = proc.poll()
                if code is not None and not _stopping:
                    log("run", f"a service exited (code {code}); stopping the rest.")
                    shutdown()
                    sys.exit(code or 0)
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
