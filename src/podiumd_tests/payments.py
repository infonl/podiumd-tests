"""Payments in Open Formulieren, with podiumd-tests playing Ogone (legacy) for the test merchant.

Open Formulieren hands the browser a form to POST to Ogone, signed with SHA-IN. Ogone sends the
browser back to one of the return URLs in that form, with the outcome signed with SHA-OUT. The
test merchant uses one passphrase for both.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlsplit

from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Mapping

    import requests

    from podiumd_tests.json_data import JsonObject

OGONE_HASH = "sha512"
# Never called: Open Formulieren only hands it to the browser.
OGONE_ENDPOINT = "https://ogone.example.invalid/ncol/test/orderstandard_utf8.asp"
# The return URL Ogone sends the browser to, per outcome.
RETURN_URLS = {"accept": "ACCEPTURL", "decline": "DECLINEURL", "exception": "EXCEPTIONURL", "cancel": "CANCELURL"}


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
