#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def load_local_env() -> None:
    for name in (".env", ".env.local"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


class HotspotHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/refresh":
            self.handle_refresh()
            return
        if path == "/api/enhance":
            self.handle_ai_action("enhance")
            return
        if path == "/api/summarize":
            self.handle_ai_action("summarize")
            return
        self.send_error(404, "Not found")

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_ai_action(self, action: str) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            self.send_json({"ok": False, "error": "OPENAI_API_KEY is not configured."}, 400)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
            index = int(payload.get("index"))
        except Exception:
            self.send_json({"ok": False, "error": "Request body must include numeric index."}, 400)
            return

        if action == "enhance":
            command = [sys.executable, "hotspot_radar.py", "--enhance-index", str(index)]
        else:
            command = [sys.executable, "hotspot_radar.py", "--summarize-index", str(index)]
        self.run_command(command, timeout=180)

    def handle_refresh(self) -> None:
        self.run_command([sys.executable, "hotspot_radar.py"], timeout=300)

    def run_command(self, command: list[str], timeout: int) -> None:
        try:
            proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
            payload = {
                "ok": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:],
                "stderr": proc.stderr[-4000:],
            }
            status = 200 if proc.returncode == 0 else 500
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            status = 500
        self.send_json(payload, status)


def main() -> int:
    load_local_env()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8010))
    server = ThreadingHTTPServer((host, port), HotspotHandler)
    print(f"Hotspot radar server: http://{host}:{port}/dashboard.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
