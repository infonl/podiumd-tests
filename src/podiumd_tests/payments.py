"""Payments in Open Formulieren, with podiumd-tests playing the payment providers for its test merchants.

Ogone (legacy): Open Formulieren hands the browser a form to POST to Ogone, signed with SHA-IN. Ogone
sends the browser back to one of the return URLs in that form, with the outcome signed with SHA-OUT.
The test merchant uses one passphrase for both.

Worldline: Open Formulieren creates a hosted checkout through Worldline's API, which the webhook
receiver plays, and sends the browser to its redirect URL. The test writes the payment's status to
the receiver and returns to Open Formulieren as Worldline would; Open Formulieren then reads the
status from the receiver.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlsplit

from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.webhook import CHECKOUTS_DIR
from podiumd_tests.webhook import NAME as RECEIVER

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

OGONE_HASH = "sha512"
# Never called: Open Formulieren only hands it to the browser.
OGONE_ENDPOINT = "https://ogone.example.invalid/ncol/test/orderstandard_utf8.asp"
# The return URL Ogone sends the browser to, per outcome.
RETURN_URLS = {"accept": "ACCEPTURL", "decline": "DECLINEURL", "exception": "EXCEPTIONURL", "cancel": "CANCELURL"}
# Where the receiver's hosted checkouts send the browser (infra/webhook-receiver/receiver.py); never visited.
WORLDLINE_REDIRECT = "https://worldline.example.invalid/hostedcheckout/"


def ogone_shasign(params: Mapping[str, object], passphrase: str) -> str:
    """Ogone's SHASIGN: the non-empty parameters sorted by name as NAME=value+passphrase, hashed."""
    pairs = sorted((k.upper(), str(v).strip()) for k, v in params.items() if k.upper() != "SHASIGN")
    text = "".join(f"{k}={v}{passphrase}" for k, v in pairs if v)
    return hashlib.new(OGONE_HASH, text.encode()).hexdigest().upper()


def ogone_feedback(order_id: str, status: str, passphrase: str) -> dict[str, str]:
    """Ogone's signed feedback on a payment, as it sends it to the return URL and the webhook."""
    feedback = {"ORDERID": order_id, "PAYID": str(secrets.randbelow(10**9)), "STATUS": status, "NCERROR": "0"}
    return {**feedback, "SHASIGN": ogone_shasign(feedback, passphrase)}


def ogone_return_url(request: Mapping[str, str], outcome: str, status: str, passphrase: str) -> str:
    """The URL Ogone sends the browser back to after the payment request: the outcome's return URL with feedback."""
    url = request[RETURN_URLS[outcome]]
    return f"{url}{'&' if '?' in url else '?'}{urlencode(ogone_feedback(request['ORDERID'], status, passphrase))}"


def form_fields(request: JsonObject) -> dict[str, str]:
    """The fields of the form a payment request posts (Ogone)."""
    return {k: str(v) for k, v in section(request, "data").items()}


def start_payment(http: requests.Session, payment_url: str, headers: Mapping[str, str]) -> JsonObject:
    """Open Formulieren's payment request for a completed submission: {type, url, data}."""
    response = http.post(payment_url, json={}, headers=dict(headers))
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def payment_return(http: requests.Session, url: str) -> dict[str, str]:
    """Follow Ogone's return; what Open Formulieren's redirect tells the form, e.g. of_payment_status."""
    response = expect_status(http.get(url, allow_redirects=False), HTTPStatus.FOUND)
    query = parse_qs(urlsplit(response.headers["Location"]).query)
    if query.get("_of_action") != ["payment"]:
        msg = f"redirect is no payment action: {response.headers['Location']}"
        raise AssertionError(msg)
    return cast("dict[str, str]", json.loads(query["_of_action_params"][0]))


def worldline_return_url(env: Environment, redirect_url: str, status: str) -> tuple[str, str]:
    """Pay at the receiver's hosted checkout with this payment status (or CANCELLED_BY_CONSUMER).

    Returns the URL Worldline sends the browser back to, and the payment's merchantReference.
    """
    checkout_id = redirect_url.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[0-9a-f]{32}", checkout_id) or not re.fullmatch(r"[A-Z_]+", status):
        msg = f"unexpected hosted checkout {redirect_url!r} or status {status!r}"
        raise ValueError(msg)
    checkout_file = f"{CHECKOUTS_DIR}/{checkout_id}"
    script = f"echo {status} > {checkout_file}.status && cat {checkout_file}.json"
    checkout = cast("dict[str, str]", json.loads(env.kube.exec(RECEIVER, "sh", "-c", script)))
    query = urlencode({"RETURNMAC": checkout["RETURNMAC"], "hostedCheckoutId": checkout_id})
    return f"{checkout['returnUrl']}?{query}", checkout["merchantReference"]


def worldline_webhook(reference: str, status: str, key_id: str, secret: str) -> tuple[bytes, dict[str, str]]:
    """Worldline's webhook event on the payment, and its signature headers."""
    event = {
        "apiVersion": "v1",
        "id": str(uuid.uuid4()),
        "merchantId": key_id,
        "type": "payment.captured",
        "payment": {
            "id": f"{uuid.uuid4().hex}_0",
            "status": status,
            "paymentOutput": {"references": {"merchantReference": reference}},
        },
    }
    body = json.dumps(event).encode()
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return body, {"Content-Type": "application/json", "X-GCS-Signature": signature, "X-GCS-KeyId": key_id}
