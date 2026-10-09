"""Unit tests for submitting an Open Formulieren form."""

import json

import pytest
import requests

from podiumd_tests.openformulieren import submit
from podiumd_tests.openformulieren import wait_for_registration
from podiumd_tests.seed.registry import ResourceRegistry

OF = "https://of.example.test"


@pytest.fixture
def env(env_factory, profile_factory):
    return env_factory(profile_factory(urls={"openformulieren": OF}))


def answers(final_status):
    return {
        "GET /api/v2/forms/klacht": (200, {"url": f"{OF}/api/v2/forms/klacht"}),
        "POST /api/v2/submissions": (
            201,
            {
                "id": "s1",
                "url": f"{OF}/api/v2/submissions/s1",
                "steps": [{"url": f"{OF}/api/v2/submissions/s1/steps/1"}],
            },
        ),
        "PUT /api/v2/submissions/s1/steps/1": (201, {}),
        "POST /api/v2/submissions/s1/_complete": (200, {"statusUrl": f"{OF}/api/v2/submissions/s1/status"}),
        "GET /api/v2/submissions/s1/status": (200, final_status),
    }


def test_submit_walks_the_sdk_sequence_and_returns_the_done_status(fake_http, env):
    sent = fake_http(answers({"status": "done", "result": "success", "publicReference": "ZAAK-1"}))
    registry = ResourceRegistry("ptest-abc", keep=True)
    status = submit(env, requests.Session(), registry, "klacht", {"veld": "x"}, timeout=0, registers=False)
    assert status["publicReference"] == "ZAAK-1"
    assert [f"{s.method} {s.url.removeprefix(OF)}" for s in sent][:4] == [
        "GET /api/v2/forms/klacht",
        "POST /api/v2/submissions",
        "PUT /api/v2/submissions/s1/steps/1",
        "POST /api/v2/submissions/s1/_complete",
    ]
    assert "X-CSRFToken" in sent[1].headers
    assert registry.cleanup() == ["submission s1"]


def test_failed_submission_names_the_submission(fake_http, env):
    fake_http(answers({"status": "failed", "errorMessage": "zaaktype not found"}))
    with pytest.raises(AssertionError, match="submission s1 failed: zaaktype not found"):
        submit(env, requests.Session(), ResourceRegistry("ptest-abc"), "klacht", {}, timeout=0)


def test_done_without_success_is_a_failed_registration(fake_http, env):
    fake_http(answers({"status": "done", "result": "failed", "errorMessage": "geen zaaktype", "publicReference": ""}))
    with pytest.raises(AssertionError, match="result 'failed', 'geen zaaktype'"):
        submit(env, requests.Session(), ResourceRegistry("ptest-abc"), "klacht", {}, timeout=0)


def test_failed_registration_in_open_formulieren_names_the_error(env, fake_runner):
    """The public status said success; Open Formulieren's own registration status says failed."""
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openformulieren"}}]}))
    value = {"status": "failed", "error": "HTTPError: 400 Client Error"}
    fake_runner.answers["exec -i deploy/openformulieren"] = (0, f"PTEST_VALUE={json.dumps(value)}\n")
    with pytest.raises(AssertionError, match="registration of submission s1 failed: HTTPError: 400"):
        wait_for_registration(env, "s1", timeout=0)
