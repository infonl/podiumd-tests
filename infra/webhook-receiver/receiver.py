"""Webhook receiver for podiumd-tests: every POST is appended to a JSON-lines file.

A POST with an Authorization header gets 204; one without gets 403. Open Notificaties checks
both when an abonnement is created: it refuses a callback that accepts requests without auth.

Standard library only. Tests read RECEIVED with `kubectl exec ... cat`; GET /healthz answers 200.
"""

import json
import os
import time

from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path

RECEIVED = Path(os.environ.get("RECEIVED_FILE", "/data/received.jsonl"))


class Handler(BaseHTTPRequestHandler):
    """POST: record, then 204 with Authorization and 403 without. GET /healthz: 200."""

    def do_POST(self):  # http.server's method name
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = body
        entry = {
            "received": time.time(),
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": parsed,
        }
        with RECEIVED.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self.send_response(204 if entry["authorization"] else 403)
        self.end_headers()

    def do_GET(self):  # http.server's method name
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *_args):
        """Keep the pod log quiet; the file is the record."""


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  # a cluster-internal service
