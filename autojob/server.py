"""`autojob serve`: local dashboard where you can mark jobs applied / ignored."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .config import Workspace
from .report import dashboard_payload, render_html
from .state import load_state, save_state, set_status

_lock = threading.Lock()


def make_handler(ws: Workspace, run_pipeline):
    class Handler(BaseHTTPRequestHandler):
        server_version = "autojob"

        def log_message(self, fmt, *args):  # quieter console
            pass

        def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _same_origin(self) -> bool:
            # Block cross-site requests from other pages open in the browser.
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and urlparse(origin).netloc != host:
                return False
            return (self.headers.get("Content-Type") or "").startswith("application/json")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, render_html(dashboard_payload(ws), live=True), "text/html; charset=utf-8")
            elif path == "/api/data":
                self._send(200, json.dumps(dashboard_payload(ws), ensure_ascii=False), "application/json")
            else:
                self._send(404, "not found")

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._same_origin():
                self._send(403, "forbidden")
                return
            if path == "/api/mark":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(min(n, 10_000)) or b"{}")
                    job_id, status = str(body["id"]), str(body["status"])
                    with _lock:
                        state = load_state(ws.state_path)
                        set_status(state, job_id, status, str(body.get("note") or ""))
                        save_state(ws.state_path, state)
                    self._send(200, json.dumps({"ok": True}), "application/json")
                except (KeyError, ValueError) as e:
                    self._send(400, f"bad request: {e}")
            elif path == "/api/run":
                if not _lock.acquire(blocking=False):
                    self._send(409, "a run is already in progress")
                    return
                try:
                    run_pipeline()
                    self._send(200, json.dumps({"ok": True}), "application/json")
                except Exception as e:
                    self._send(500, f"{type(e).__name__}: {e}")
                finally:
                    _lock.release()
            else:
                self._send(404, "not found")

    return Handler


def serve(ws: Workspace, host: str, port: int, run_pipeline) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(ws, run_pipeline))
    print(f"AutoJob dashboard: http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
