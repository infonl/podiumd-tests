"""Unit tests for playing Ogone: SHASIGN, the return URL and Open Formulieren's redirect."""

import hashlib
import json

from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlsplit

import pytest

from podiumd_tests.payments import ogone_feedback
from podiumd_tests.payments import ogone_return_url
from podiumd_tests.payments import ogone_shasign
from podiumd_tests.payments import payment_return

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
