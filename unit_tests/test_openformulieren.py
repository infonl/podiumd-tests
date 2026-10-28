"""Unit tests for submitting an Open Formulieren form."""

import json

import pytest
import requests

from podiumd_tests import wait
from podiumd_tests.bootstrap.steps import OF_REDACTEUR
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.credentials import env_var_name
from podiumd_tests.openformulieren import download_report
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import redacteur_session
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.openformulieren import tagged_forms
from podiumd_tests.openformulieren import wait_for_registration
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.wait import Clock

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


def test_submit_walks_the_sdk_sequence_and_returns_the_done_status(fake_http, env, fake_runner):
    snippet_answers(fake_runner, None)
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


def test_submit_waits_out_the_completion_throttle(fake_http, env, fake_runner, monkeypatch):
    snippet_answers(fake_runner, None)
    monkeypatch.setattr(wait, "Clock", lambda: Clock(sleep=lambda _seconds: None))
    completions = iter([(429, {"code": "throttled"}), (200, {"statusUrl": f"{OF}/api/v2/submissions/s1/status"})])

    table = answers({"status": "done", "result": "success", "publicReference": "ZAAK-1"})

    class Throttled:
        """fake_http's answer table; _complete answers 429 first."""

        @staticmethod
        def get(key, default=None):
            return next(completions) if key == "POST /api/v2/submissions/s1/_complete" else table.get(key, default)

    sent = fake_http(Throttled())
    status = submit(
        env, requests.Session(), ResourceRegistry("ptest-abc", keep=True), "klacht", {}, timeout=5, registers=False
    )
    assert status["publicReference"] == "ZAAK-1"
    assert [s.url for s in sent].count(f"{OF}/api/v2/submissions/s1/_complete") == 2


def test_failed_submission_names_the_submission(fake_http, env, fake_runner):
    snippet_answers(fake_runner, None)
    fake_http(answers({"status": "failed", "errorMessage": "zaaktype not found"}))
    with pytest.raises(AssertionError, match="submission s1 failed: zaaktype not found"):
        submit(env, requests.Session(), ResourceRegistry("ptest-abc"), "klacht", {}, timeout=0)


def test_done_without_success_is_a_failed_registration(fake_http, env, fake_runner):
    snippet_answers(fake_runner, None)
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


def test_failed_report_download_says_what_the_web_pod_has(fake_http, env, fake_runner):
    fake_http({"GET /submissions/pdf/3/t/download": (404, {})})
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openformulieren"}}]}))
    value = {"report": True, "file": "submission-reports/2026/10/15/r.pdf", "on_disk": False}
    fake_runner.answers["exec -i deploy/openformulieren"] = (0, f"PTEST_VALUE={json.dumps(value)}\n")
    status = {"submission": "s1", "reportDownloadUrl": f"{OF}/submissions/pdf/3/t/download"}
    with pytest.raises(AssertionError, match=r"HTTP 404; Open Formulieren web pod: .*'on_disk': False"):
        download_report(env, requests.Session(), status)


def snippet_answers(fake_runner, value):
    """Every openformulieren snippet answers value."""
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openformulieren"}}]}))
    fake_runner.answers["exec -i deploy/openformulieren"] = (0, f"PTEST_VALUE={json.dumps(value)}\n")


def test_submit_that_registers_waits_for_open_formulierens_registration(fake_http, env, fake_runner):
    fake_http(answers({"status": "done", "result": "success", "publicReference": "ZAAK-1"}))
    snippet_answers(fake_runner, {"status": "success", "error": ""})
    status = submit(env, requests.Session(), ResourceRegistry("ptest-abc", keep=True), "klacht", {}, timeout=0)
    assert status["submission"] == "s1"
    assert '"action": "registration"' in fake_runner.stdins[-1]


def test_download_report_returns_the_pdf(fake_http, env):
    fake_http({"GET /submissions/pdf/3/t/download": (200, {"pdf": 1})})
    status = {"submission": "s1", "reportDownloadUrl": f"{OF}/submissions/pdf/3/t/download"}
    assert download_report(env, requests.Session(), status) == b'{"pdf": 1}'


@pytest.mark.parametrize(("found", "error"), [(1, None), (0, "0 zaken with identificatie ZAAK-1")])
def test_registered_zaak_and_its_cleanup(fake_http, env, fake_runner, found, error):
    zaak = {"url": "https://oz.test/zaken/api/v1/zaken/1"}
    sent = fake_http(
        {
            "GET /zaken/api/v1/zaken": (200, [zaak] * found),
            "GET /zaken/api/v1/zaakinformatieobjecten": (200, []),
            "DELETE /zaken/api/v1/zaken/1": (204, None),
        }
    )
    snippet_answers(fake_runner, None)
    registry = ResourceRegistry("ptest-abc")
    openzaak = ApiClient(requests.Session(), "https://oz.test", {})
    status = {"submission": "s1", "publicReference": "ZAAK-1"}
    if error:
        with pytest.raises(AssertionError, match=error):
            registered_zaak(env, openzaak, registry, status)
    else:
        assert registered_zaak(env, openzaak, registry, status) == zaak
    assert registry.cleanup() == []
    assert '"action": "delete"' in fake_runner.stdins[-1]
    assert [s.method for s in sent].count("DELETE") == found


def test_make_form_applies_the_snippet_and_cleanup_removes_the_form(env, fake_runner):
    snippet_answers(fake_runner, None)
    registry = ResourceRegistry("ptest-abc")
    make_form(env, registry, "ptest-form", [{"key": "naam"}], {"backend": "zgw"}, ("digid",), confirmation=True)
    params = fake_runner.stdins[-1]
    assert '"action": "apply"' in params
    assert '"auth_backends": ["digid"]' in params
    assert '"settings": {"confirmation": true}' in params
    assert registry.cleanup() == []
    assert '"action": "remove"' in fake_runner.stdins[-1]


def test_tagged_forms(env, fake_runner):
    snippet_answers(fake_runner, ["ptest-a", "ptest-b"])
    assert tagged_forms(env) == ["ptest-a", "ptest-b"]


def test_redacteur_session_carries_the_api_token(env_factory, profile_factory):
    environ = {env_var_name(str(OF_REDACTEUR.store_key)): "t0ken"}
    http = redacteur_session(env_factory(profile_factory(urls={"openformulieren": OF}), environ))
    assert http.headers["Authorization"] == "Token t0ken"
