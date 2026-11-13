"""Mock server for podiumd-tests: every POST is appended to a JSON-lines file.

A POST with an Authorization header gets 204; one without gets 403. Open Notificaties checks
both when an abonnement is created: it refuses a callback that accepts requests without auth.
It also stands in for Notify (NotifyNL): a POST to .../v2/notifications/email or /sms gets
the 201 and notification JSON a Notify client expects, and the entry records the notification's
"id"; GET .../v2/notifications/<id> answers with that notification. POST .../v2/template/<id>/preview gets
200 and a preview, whose subject and body are "ptest preview <id>". On a path with /fail-first/ the first
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

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Lock

WRITE_LOCK = Lock()
FAILED_ONCE: set[str] = set()
RECEIVED = Path(os.environ.get("RECEIVED_FILE", "/data/received.jsonl"))
CHECKOUTS = Path(os.environ.get("CHECKOUTS_DIR", "/data/worldline"))
HOSTED_CHECKOUT = re.compile(r"^/v2/[^/]+/hostedcheckouts(?:/([0-9a-f]+))?$")
NOTIFICATION = re.compile(r"/v2/notifications/([0-9a-f-]{36})$")
PREVIEW = re.compile(r"/v2/template/([0-9a-f-]{36})/preview$")
NOTIFICATIONS: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    """POST: record, then 204 (Notify: 201, a preview 200) with Authorization and 403 without. GET /healthz: 200."""

    def do_POST(self) -> None:  # http.server's method name
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
        if "/v2/notifications/" in self.path:
            entry["id"] = str(uuid.uuid4())
        try:
            # One write per request under a lock: parallel requests never interleave lines.
            with WRITE_LOCK, RECEIVED.open("a", encoding="utf-8") as handle:
                entry["status"] = self.answer_status(entry)
                handle.write(f"{json.dumps(entry)}\n")
        except OSError:
            # Not recorded (e.g. a full disk): say so instead of dropping the connection.
            self.send_response(507)
            self.end_headers()
            return
        self._answer(entry)

    def do_GET(self) -> None:  # http.server's method name
        notification = NOTIFICATION.search(self.path)
        if notification and notification[1] in NOTIFICATIONS:
            self.send_json(200, NOTIFICATIONS[notification[1]])
            return
        found = HOSTED_CHECKOUT.match(self.path)
        if found and found[1] and (CHECKOUTS / f"{found[1]}.json").exists():
            self.send_json(200, _checkout_status(found[1]))
            return
        self.send_response(200 if self.path == "/healthz" else 404)
        self.end_headers()

    def log_message(self, *_args) -> None:
        """Keep the pod log quiet; the file is the record."""

    def answer_status(self, entry) -> int:
        """Return the answer to a POST; called under WRITE_LOCK."""
        if not entry["authorization"]:
            return 403
        if "/v2/notifications/" in self.path:
            return 201
        if PREVIEW.search(self.path):
            return 200
        body = entry["body"]
        check = isinstance(body, dict) and body.get("kanaal") == "test"
        if "/fail-first/" in self.path and not check and self.path not in FAILED_ONCE:
            FAILED_ONCE.add(self.path)
            return 500
        return 204

    def notify_created(self, notification_id, request) -> None:
        template = request.get("template_id")
        kind = "sms" if self.path.endswith("/sms") else "email"
        subject = f"ptest {kind} {template}"
        NOTIFICATIONS[notification_id] = {
            "id": notification_id,
            "reference": request.get("reference"),
            "email_address": request.get("email_address"),
            "phone_number": request.get("phone_number"),
            "type": kind,
            "status": "delivered",
            "template": {"id": template, "version": 1, "uri": f"/v2/template/{template}"},
            "body": subject,
            "subject": subject,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
        }
        self.send_json(
            201,
            {
                "id": notification_id,
                "reference": request.get("reference"),
                "uri": f"{self.path}/{notification_id}",
                "template": NOTIFICATIONS[notification_id]["template"],
                "content": {"body": subject, "subject": subject, "from_email": "", "from_number": ""},
            },
        )

    def send_json(self, status, body) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _answer(self, entry) -> None:
        """Send the answer to a recorded POST: Notify's JSON, or its status alone."""
        preview = PREVIEW.search(self.path)
        if entry["status"] == HTTPStatus.CREATED:
            self.notify_created(entry["id"], entry["body"] if isinstance(entry["body"], dict) else {})
        elif preview and entry["status"] == HTTPStatus.OK:
            subject = f"ptest preview {preview[1]}"
            self.send_json(200, {"id": preview[1], "type": "email", "version": 1, "body": subject, "subject": subject})
        else:
            self.send_response(entry["status"])
            self.end_headers()

    def _create_checkout(self, request) -> None:
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
        self.send_json(201, {**body, "redirectUrl": redirect})


def _checkout_status(checkout_id) -> dict[str, object]:
    status_file = CHECKOUTS / f"{checkout_id}.status"
    status = status_file.read_text(encoding="utf-8").strip() if status_file.exists() else "IN_PROGRESS"
    if status in {"IN_PROGRESS", "CANCELLED_BY_CONSUMER"}:
        return {"status": status}
    payment = {"id": f"{checkout_id}_0", "status": status}
    return {"status": "PAYMENT_CREATED", "createdPaymentOutput": {"payment": payment}}


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # noqa: S104  # a cluster-internal service
