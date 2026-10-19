"""Unit tests for the Mailpit helpers."""

import json

import pytest
import requests

from podiumd_tests.capabilities import Capabilities
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.mailpit import delete_message
from podiumd_tests.mailpit import forget_mails
from podiumd_tests.mailpit import mail_queue
from podiumd_tests.mailpit import received
from podiumd_tests.mailpit import wait_for_mail
from podiumd_tests.seed.registry import ResourceRegistry

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


def test_received_returns_the_html_and_cleanup_deletes_mails_to_the_address(fake_http):
    sent = fake_http(
        {
            "GET /api/v1/search": (200, {"messages": [{"ID": "a", "Subject": "s"}]}),
            "GET /api/v1/message/a": (200, {"HTML": "<p>hoi</p>"}),
            "DELETE /api/v1/search": (200, {}),
        }
    )
    registry = ResourceRegistry("ptest-abc")
    assert received(ApiClient(requests.Session(), API, {}), registry, timeout=0, to="x@example.invalid") == "<p>hoi</p>"
    assert registry.cleanup() == []
    assert sent[-1].method == "DELETE"
    assert "to%3A%22x%40example.invalid%22" in sent[-1].url


@pytest.mark.parametrize(("present", "registered"), [(frozenset({"mailpit"}), 1), (frozenset(), 0)])
def test_forget_mails_only_where_the_environment_has_mailpit(env_factory, profile_factory, present, registered):
    env = env_factory(profile_factory(urls={"mailpit": "https://mailpit.example.test"}))
    env.__dict__["capabilities"] = Capabilities(present, {})
    registry = ResourceRegistry("ptest-abc", keep=True)
    forget_mails(env, registry, "subject:x")
    assert len(registry) == registered


def test_mail_queue_returns_the_statuses(env_factory, fake_runner):
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openformulieren"}}]}))
    fake_runner.answers["exec -i deploy/openformulieren"] = (0, 'PTEST_VALUE={"status": ["queued"]}\n')
    assert mail_queue(env_factory(), "openformulieren", "status", "x") == ["queued"]
    assert '"action": "status"' in fake_runner.stdins[-1]
