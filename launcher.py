"""Single-window launcher for Translatale backend and frontend with prefixed logs."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

_PRINT_LOCK = threading.Lock()


def _log(prefix: str, line: str) -> None:
    with _PRINT_LOCK:
        print(f"[{prefix}] {line}", flush=True)


def _stream_output(proc: subprocess.Popen[str], prefix: str) -> None:
    assert proc.stdout is not None
    try:
        for raw_line in iter(proc.stdout.readline, ""):
            line = raw_line.rstrip("\r\n")
            if line:
                _log(prefix, line)
    except Exception:
        pass


def _kill_tree(proc: subprocess.Popen[str] | None, name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    _log("SYS", f"Menghentikan {name} (PID {proc.pid})...")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _wait_and_open_browser(url: str, stop_event: threading.Event) -> None:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not stop_event.is_set():
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1):
                break
        except Exception:
            time.sleep(0.5)
    if not stop_event.is_set():
        time.sleep(1.0)
        _log("SYS", f"Membuka browser: {url}")
        webbrowser.open(url)


def main() -> int:
    uvicorn_exe = BACKEND_DIR / ".venv" / "Scripts" / "uvicorn.exe"
    if not uvicorn_exe.exists():
        uvicorn_cmd = [sys.executable, "-m", "uvicorn"]
    else:
        uvicorn_cmd = [str(uvicorn_exe)]

    be_cmd = [*uvicorn_cmd, "main:app", "--reload", "--port", "8000"]
    fe_cmd = ["npm.cmd" if os.name == "nt" else "npm", "run", "dev"]

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["FORCE_COLOR"] = "0"
    env["NO_COLOR"] = "1"

    _log("SYS", "Menjalankan Backend (port 8000) dan Frontend (port 5173)...")
    _log("SYS", "Tekan Ctrl+C atau tutup window ini untuk menghentikan keduanya.")

    be_proc = subprocess.Popen(
        be_cmd,
        cwd=str(BACKEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=creationflags,
    )
    fe_proc = subprocess.Popen(
        fe_cmd,
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=creationflags,
    )

    stop_event = threading.Event()

    def _handle_signal(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle_signal)

    threads = [
        threading.Thread(target=_stream_output, args=(be_proc, "BE"), daemon=True),
        threading.Thread(target=_stream_output, args=(fe_proc, "FE"), daemon=True),
        threading.Thread(
            target=_wait_and_open_browser,
            args=("http://localhost:5173", stop_event),
            daemon=True,
        ),
    ]
    for t in threads:
        t.start()

    try:
        while not stop_event.is_set():
            be_code = be_proc.poll()
            fe_code = fe_proc.poll()
            if be_code is not None:
                _log("SYS", f"Backend berhenti dengan kode {be_code}.")
                break
            if fe_code is not None:
                _log("SYS", f"Frontend berhenti dengan kode {fe_code}.")
                break
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        _kill_tree(fe_proc, "Frontend")
        _kill_tree(be_proc, "Backend")
        _log("SYS", "Semua server telah dihentikan.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
