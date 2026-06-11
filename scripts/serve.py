#!/usr/bin/env python3
"""Sweepstake web server: static site + shared draw-night state.

Serves docs/ like `python3 -m http.server` but adds a tiny JSON API so that
when someone spins the wheel on draw.html, every other open browser sees the
same draw unfold live:

    GET  /api/draw            -> {"seq": N, "events": [...]}    (poll ~1s)
    GET  /api/draw?since=N    -> only events after seq N
    POST /api/draw            -> append an event  {"type": "spin"|"lock"|...}
    POST /api/draw/reset      -> wipe the draw and start over

State survives restarts in var/draw_state.json. Stdlib only.

Usage:  python3 scripts/serve.py [port]      (default 8123)
"""
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATE_FILE = ROOT / "var" / "draw_state.json"

_lock = threading.Lock()
_state = {"seq": 0, "events": []}


def load_state():
    global _state
    if STATE_FILE.exists():
        try:
            _state = json.loads(STATE_FILE.read_text())
        except Exception:
            pass


def save_state():
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(_state))


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs: only API + errors
        if "/api/" in (args[0] if args else "") or "404" in str(args[1:2]):
            super().log_message(fmt, *args)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/draw":
            since = 0
            if "since=" in self.path:
                try:
                    since = int(self.path.split("since=")[1].split("&")[0])
                except ValueError:
                    pass
            with _lock:
                events = [e for e in _state["events"] if e["seq"] > since]
                return self._json({"seq": _state["seq"], "events": events})
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/draw/reset":
            with _lock:
                _state["seq"] += 1
                _state["events"] = [{"seq": _state["seq"], "type": "reset"}]
                save_state()
                return self._json({"seq": _state["seq"]})
        if path == "/api/draw":
            try:
                length = int(self.headers.get("Content-Length", 0))
                ev = json.loads(self.rfile.read(length))
                assert isinstance(ev, dict) and isinstance(ev.get("type"), str)
            except Exception:
                return self._json({"error": "bad event"}, 400)
            with _lock:
                _state["seq"] += 1
                ev["seq"] = _state["seq"]
                _state["events"].append(ev)
                # a fresh draw makes older history irrelevant; cap memory
                if len(_state["events"]) > 500:
                    _state["events"] = _state["events"][-500:]
                save_state()
                return self._json({"seq": _state["seq"]})
        return self._json({"error": "not found"}, 404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    load_state()
    server = ThreadingHTTPServer(("", port), partial(Handler, directory=str(DOCS)))
    print(f"Serving {DOCS} + draw API on http://0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
