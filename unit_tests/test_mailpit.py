"""Unit tests for the Mailpit helpers."""

import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.mailpit import delete_message
from podiumd_tests.mailpit import wait_for_subject

API = "https://mailpit.example.test/api/v1"


def test_wait_for_subject_skips_partial_matches(fake_http):
    messages = [{"ID": "a", "Subject": "run1-mail-x extra"}, {"ID": "b", "Subject": "run1-mail-x"}]
    fake_http({"GET /api/v1/search": (200, {"messages": messages})})
    assert wait_for_subject(ApiClient(requests.Session(), API, {}), "run1-mail-x", timeout=0)["ID"] == "b"


def test_delete_message_sends_its_id(fake_http):
    sent = fake_http({"DELETE /api/v1/messages": (200, {})})
    delete_message(ApiClient(requests.Session(), API, {}), "b")
    assert [s.method for s in sent] == ["DELETE"]
