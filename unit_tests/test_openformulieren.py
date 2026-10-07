"""Unit tests for submitting an Open Formulieren form."""

import pytest
import requests

from podiumd_tests.openformulieren import submit

OF = "https://of.example.test"


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


def test_submit_walks_the_sdk_sequence_and_returns_the_done_status(fake_http):
    sent = fake_http(answers({"status": "done", "result": "success", "publicReference": "ZAAK-1"}))
    status = submit(requests.Session(), OF, "klacht", {"veld": "x"}, timeout=0)
    assert status["publicReference"] == "ZAAK-1"
    assert [f"{s.method} {s.url.removeprefix(OF)}" for s in sent][:4] == [
        "GET /api/v2/forms/klacht",
        "POST /api/v2/submissions",
        "PUT /api/v2/submissions/s1/steps/1",
        "POST /api/v2/submissions/s1/_complete",
    ]
    assert "X-CSRFToken" in sent[1].headers


def test_failed_registration_names_the_submission(fake_http):
    fake_http(answers({"status": "failed", "errorMessage": "zaaktype not found"}))
    with pytest.raises(AssertionError, match="submission s1 failed: zaaktype not found"):
        submit(requests.Session(), OF, "klacht", {}, timeout=0)


def test_done_without_success_is_a_failed_registration(fake_http):
    fake_http(answers({"status": "done", "result": "failed", "errorMessage": "geen zaaktype", "publicReference": ""}))
    with pytest.raises(AssertionError, match="result 'failed', 'geen zaaktype'"):
        submit(requests.Session(), OF, "klacht", {}, timeout=0)
