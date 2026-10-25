from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            env[key.strip()] = value
    return env


def main() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        print("No .env found. Copy .env.example to .env first.")
        raise SystemExit(1)

    env = load_env(env_file)
    app_url = env.get("CLYP_APP_URL", "http://127.0.0.1:8080")
    ai_url = env.get("CLYP_AI_ENDPOINT", "http://127.0.0.1:8100")

    ai = subprocess.Popen([sys.executable, "ai_service.py"], cwd=ROOT, env=env)
    web = subprocess.Popen([sys.executable, "web_service.py"], cwd=ROOT, env=env)
    procs = [ai, web]

    def stop(*_args):
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    time.sleep(0.8)
    if any(proc.poll() is not None for proc in procs):
        stop()

    print("\nClyp Design Studio V4 is running:")
    print(f"Web:      {app_url}")
    print(f"AI:       {ai_url.rstrip('/')}/health")
    print("Storage:  Designs in browser storage, videos in storage/video")
    print("Video:    Needs FFmpeg (CLYP_FFMPEG_PATH or PATH)")
    print("Assets:   Local upload + AI image + Openverse search")
    print("Accounts: Disabled for this development phase")
    print("MySQL:    Not required")
    print("XAMPP:    Not required")
    print("\nPress Ctrl+C to stop Clyp.\n")

    try:
        webbrowser.open(app_url)
    except Exception:
        pass

    while True:
        if any(proc.poll() is not None for proc in procs):
            stop()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
