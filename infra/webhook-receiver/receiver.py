"""Webhook receiver for podiumd-tests: every POST is appended to a JSON-lines file.

A POST with an Authorization header gets 204; one without gets 403. Open Notificaties checks
both when an abonnement is created: it refuses a callback that accepts requests without auth.
It also stands in for Notify (NotifyNL): a POST to .../v2/notifications/email or /sms gets
the 201 and notification JSON a Notify client expects.

Standard library only. Tests read RECEIVED with `kubectl exec ... cat`; GET /healthz answers 200.
"""

import json
import os
import time
import uuid

from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Lock

WRITE_LOCK = Lock()
RECEIVED = Path(os.environ.get("RECEIVED_FILE", "/data/received.jsonl"))


class Handler(BaseHTTPRequestHandler):
    """POST: record, then 204 (Notify: 201) with Authorization and 403 without. GET /healthz: 200."""

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
        try:
            # One write per request under a lock: parallel requests never interleave lines.
            with WRITE_LOCK, RECEIVED.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            # Not recorded (e.g. a full disk): say so instead of dropping the connection.
            self.send_response(507)
            self.end_headers()
            return
        if not entry["authorization"]:
            self.send_response(403)
            self.end_headers()
        elif "/v2/notifications/" in self.path:
            self._notify_created(parsed if isinstance(parsed, dict) else {})
        else:
            self.send_response(204)
            self.end_headers()

    def _notify_created(self, request):
        template = request.get("template_id")
        notification = {
            "id": str(uuid.uuid4()),
            "reference": request.get("reference"),
            "uri": f"{self.path}/{uuid.uuid4()}",
            "template": {"id": template, "version": 1, "uri": f"/v2/template/{template}"},
            "content": {"body": "", "subject": "", "from_email": "", "from_number": ""},
        }
        payload = json.dumps(notification).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # http.server's method name
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *_args):
        """Keep the pod log quiet; the file is the record."""


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  # a cluster-internal service
