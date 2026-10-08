"""Unit tests for the Mailpit helpers."""

import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.mailpit import delete_message
from podiumd_tests.mailpit import wait_for_mail

API = "https://mailpit.example.test/api/v1"


def test_wait_for_mail_skips_partial_subject_matches(fake_http):
    messages = [{"ID": "a", "Subject": "run1-mail-x extra"}, {"ID": "b", "Subject": "run1-mail-x"}]
    fake_http({"GET /api/v1/search": (200, {"messages": messages})})
    assert wait_for_mail(ApiClient(requests.Session(), API, {}), timeout=0, subject="run1-mail-x")["ID"] == "b"


def test_wait_for_mail_to_an_address_takes_any_subject(fake_http):
    sent = fake_http({"GET /api/v1/search": (200, {"messages": [{"ID": "a", "Subject": "Opgeslagen formulier"}]})})
    assert wait_for_mail(ApiClient(requests.Session(), API, {}), timeout=0, to="x@example.invalid")["ID"] == "a"
    assert "to%3A%22x%40example.invalid%22" in sent[0].url


def test_delete_message_sends_its_id(fake_http):
    sent = fake_http({"DELETE /api/v1/messages": (200, {})})
    delete_message(ApiClient(requests.Session(), API, {}), "b")
    assert [s.method for s in sent] == ["DELETE"]
