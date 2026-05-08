#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent

class HotspotHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/refresh":
            self.send_error(404, "Not found")
            return
        command = [sys.executable, "hotspot_radar.py"]
        if self.headers.get("X-AI-Refresh") == "1":
            command.extend(["--ai", "--ai-limit", self.headers.get("X-AI-Limit", os.environ.get("AI_LIMIT", "3"))])
        try:
            proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
            payload = {"ok": proc.returncode == 0, "returncode": proc.returncode, "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
            status = 200 if proc.returncode == 0 else 500
        except Exception as exc:
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            status = 500
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def main() -> int:
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
