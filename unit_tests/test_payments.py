"""Unit tests for playing Ogone: SHASIGN, the return URL and Open Formulieren's redirect."""

import base64
import hashlib
import hmac
import json

from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlsplit

import pytest

from podiumd_tests.payments import WORLDLINE_REDIRECT
from podiumd_tests.payments import ogone_feedback
from podiumd_tests.payments import ogone_return_url
from podiumd_tests.payments import ogone_shasign
from podiumd_tests.payments import payment_return
from podiumd_tests.payments import worldline_return_url
from podiumd_tests.payments import worldline_webhook

if TYPE_CHECKING:
    import requests


def test_shasign_sorts_uppercased_names_and_skips_empty_values_and_itself():
    expected = hashlib.sha512(b"AMOUNT=1250pwORDERID=OF-1pw").hexdigest().upper()
    assert ogone_shasign({"orderID": "OF-1", "AMOUNT": 1250, "TITLE": " ", "SHASIGN": "x"}, "pw") == expected


def test_feedback_is_signed():
    feedback = ogone_feedback("OF-1", "9", "pw")
    assert (feedback["ORDERID"], feedback["STATUS"]) == ("OF-1", "9")
    assert feedback["SHASIGN"] == ogone_shasign(feedback, "pw")


@pytest.mark.parametrize(
    ("outcome", "base"),
    [("accept", "https://of.test/payment/1/return?action=accept"), ("cancel", "https://of.test/payment/1/return")],
)
def test_return_url_is_the_outcomes_url_with_the_feedback(outcome, base):
    request = {"ORDERID": "OF-1", "ACCEPTURL": base, "CANCELURL": base}
    url = ogone_return_url(request, outcome, "9", "pw")
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(base)
    assert query["SHASIGN"] == ogone_shasign({k: v for k, v in query.items() if k != "action"}, "pw")


def test_payment_return_reads_the_forms_action_params(response_factory):
    params = {"of_payment_status": "completed"}
    location = "https://of.test/form/?" + urlencode({"_of_action": "payment", "_of_action_params": json.dumps(params)})
    response = response_factory(status=302)
    response.headers["Location"] = location

    class Http:
        def get(self, url, *, allow_redirects):
            assert (url, allow_redirects) == ("https://of.test/payment/1/return", False)
            return response

    assert payment_return(cast("requests.Session", Http()), "https://of.test/payment/1/return") == params


CHECKOUT = "0123456789abcdef0123456789abcdef"


def test_worldline_return_writes_the_status_and_returns_as_worldline(env_factory, fake_runner):
    checkout = {"returnUrl": "https://of.test/payment/1/return", "RETURNMAC": "mac", "merchantReference": "OF-1"}
    fake_runner.answers["exec deploy/ptest-bootstrap-webhook-receiver"] = (0, json.dumps(checkout))
    url, reference = worldline_return_url(env_factory(), WORLDLINE_REDIRECT + CHECKOUT, "CAPTURED")
    assert url == f"https://of.test/payment/1/return?RETURNMAC=mac&hostedCheckoutId={CHECKOUT}"
    assert reference == "OF-1"
    assert fake_runner.calls[-1][-1] == (
        f"echo CAPTURED > /data/worldline/{CHECKOUT}.status && cat /data/worldline/{CHECKOUT}.json"
    )


@pytest.mark.parametrize(
    ("checkout", "status"), [("x; rm -rf /", "CAPTURED"), (CHECKOUT, "CAPTURED; id")], ids=["checkout", "status"]
)
def test_worldline_return_refuses_what_it_would_put_in_a_shell(env_factory, checkout, status):
    with pytest.raises(ValueError, match="unexpected hosted checkout"):
        worldline_return_url(env_factory(), WORLDLINE_REDIRECT + checkout, status)


def test_worldline_webhook_is_signed_as_the_sdk_checks():
    body, headers = worldline_webhook("OF-1", "CAPTURED", "key", "secret")
    expected = base64.b64encode(hmac.new(b"secret", body, hashlib.sha256).digest()).decode()
    assert (headers["X-GCS-Signature"], headers["X-GCS-KeyId"]) == (expected, "key")
    event = json.loads(body)
    assert (event["apiVersion"], event["payment"]["paymentOutput"]["references"]["merchantReference"]) == ("v1", "OF-1")
