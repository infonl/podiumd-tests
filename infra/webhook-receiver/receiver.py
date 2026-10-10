"""Webhook receiver for podiumd-tests: every POST is appended to a JSON-lines file.

A POST with an Authorization header gets 204; one without gets 403. Open Notificaties checks
both when an abonnement is created: it refuses a callback that accepts requests without auth.
It also stands in for Notify (NotifyNL): a POST to .../v2/notifications/email or /sms gets
the 201 and notification JSON a Notify client expects. On a path with /fail-first/ the first
notification (not Open Notificaties' kanaal "test" check) gets 500, to test redelivery.
Each recorded entry carries the status it got.

It also stands in for Worldline's Hosted Checkout API (Open Formulieren's worldline plugin):
POST /v2/<pspid>/hostedcheckouts writes the checkout to CHECKOUTS/<id>.json; GET
/v2/<pspid>/hostedcheckouts/<id> answers with the payment status a test wrote to
CHECKOUTS/<id>.status (IN_PROGRESS while there is none). These are not recorded.

Standard library only. Tests read RECEIVED with `kubectl exec ... cat`; GET /healthz answers 200.
"""

import json
import os
import re
import time
import uuid

from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Lock

WRITE_LOCK = Lock()
FAILED_ONCE: set[str] = set()
RECEIVED = Path(os.environ.get("RECEIVED_FILE", "/data/received.jsonl"))
CHECKOUTS = Path(os.environ.get("CHECKOUTS_DIR", "/data/worldline"))
HOSTED_CHECKOUT = re.compile(r"^/v2/[^/]+/hostedcheckouts(?:/([0-9a-f]+))?$")


class Handler(BaseHTTPRequestHandler):
    """POST: record, then 204 (Notify: 201) with Authorization and 403 without. GET /healthz: 200."""

    def do_POST(self):  # http.server's method name
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        if HOSTED_CHECKOUT.match(self.path):
            self._create_checkout(json.loads(body))
            return
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
                entry["status"] = self._status(entry)
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            # Not recorded (e.g. a full disk): say so instead of dropping the connection.
            self.send_response(507)
            self.end_headers()
            return
        if entry["status"] == 201:
            self._notify_created(parsed if isinstance(parsed, dict) else {})
        else:
            self.send_response(entry["status"])
            self.end_headers()

    def _status(self, entry):
        """The answer to a POST; called under WRITE_LOCK."""
        if not entry["authorization"]:
            return 403
        if "/v2/notifications/" in self.path:
            return 201
        body = entry["body"]
        check = isinstance(body, dict) and body.get("kanaal") == "test"
        if "/fail-first/" in self.path and not check and self.path not in FAILED_ONCE:
            FAILED_ONCE.add(self.path)
            return 500
        return 204

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

    def _json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _create_checkout(self, request):
        checkout_id, mac = uuid.uuid4().hex, uuid.uuid4().hex
        reference = request["order"]["references"]["merchantReference"]
        checkout = {
            "returnUrl": request["hostedCheckoutSpecificInput"]["returnUrl"],
            "RETURNMAC": mac,
            "merchantReference": reference,
        }
        CHECKOUTS.mkdir(parents=True, exist_ok=True)
        (CHECKOUTS / f"{checkout_id}.json").write_text(json.dumps(checkout), encoding="utf-8")
        redirect = f"https://worldline.example.invalid/hostedcheckout/{checkout_id}"
        body = {"hostedCheckoutId": checkout_id, "RETURNMAC": mac, "merchantReference": reference}
        self._json(201, {**body, "redirectUrl": redirect})

    def _checkout_status(self, checkout_id):
        status_file = CHECKOUTS / f"{checkout_id}.status"
        status = status_file.read_text(encoding="utf-8").strip() if status_file.exists() else "IN_PROGRESS"
        if status in {"IN_PROGRESS", "CANCELLED_BY_CONSUMER"}:
            return {"status": status}
        payment = {"id": f"{checkout_id}_0", "status": status}
        return {"status": "PAYMENT_CREATED", "createdPaymentOutput": {"payment": payment}}

    def do_GET(self):  # http.server's method name
        found = HOSTED_CHECKOUT.match(self.path)
        if found and found[1] and (CHECKOUTS / f"{found[1]}.json").exists():
            self._json(200, self._checkout_status(found[1]))
            return
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *_args):
        """Keep the pod log quiet; the file is the record."""


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  # a cluster-internal service
