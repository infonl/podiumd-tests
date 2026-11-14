"""Unit tests for submitting an Open Formulieren form."""

import json
import re

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import requests

from podiumd_tests import openformulieren
from podiumd_tests import wait
from podiumd_tests.bootstrap.steps import OF_PREFILL
from podiumd_tests.bootstrap.steps import OF_REDACTEUR
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.credentials import env_var_name
from podiumd_tests.openformulieren import REPORT_RETRIES
from podiumd_tests.openformulieren import download_report
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import redacteur_session
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.openformulieren import tagged_forms
from podiumd_tests.openformulieren import wait_for_registration
from podiumd_tests.seed.registry import ResourceRegistry
from podiumd_tests.wait import Clock

if TYPE_CHECKING:
    from collections.abc import Iterator

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


class Throttled:
    """fake_http's answer table; _complete answers the next of completions."""

    def __init__(self, completions, table):
        self.completions: Iterator[tuple[int, object]] = completions
        self.table: dict[str, object] = table

    def get(self, key, default=None):
        if key == "POST /api/v2/submissions/s1/_complete":
            return next(self.completions)
        return self.table.get(key, default)


def test_submit_waits_out_the_completion_throttle(fake_http, env, fake_runner, monkeypatch):
    snippet_answers(fake_runner, None)
    monkeypatch.setattr(wait, "Clock", lambda: Clock(sleep=lambda _seconds: None))
    completions = iter([(429, {"code": "throttled"}), (200, {"statusUrl": f"{OF}/api/v2/submissions/s1/status"})])

    table = answers({"status": "done", "result": "success", "publicReference": "ZAAK-1"})

    sent = fake_http(Throttled(completions, table))
    status = submit(
        env, requests.Session(), ResourceRegistry("ptest-abc", keep=True), "klacht", {}, timeout=5, registers=False
    )
    assert status["publicReference"] == "ZAAK-1"
    assert [s.url for s in sent].count(f"{OF}/api/v2/submissions/s1/_complete") == 2


def test_submission_action_waits_the_retry_after_of_a_429(response_factory, monkeypatch):
    slept = []
    monkeypatch.setattr(wait, "Clock", lambda: Clock(sleep=slept.append))
    throttled = response_factory(status=429, json_body={"code": "throttled"})
    throttled.headers["Retry-After"] = "17"
    answers = iter([throttled, response_factory(status=400, json_body={})])
    http = requests.Session()
    monkeypatch.setattr(http, "post", lambda *_args, **_kwargs: next(answers))
    submission = {"url": f"{OF}/api/v2/submissions/s1"}
    response = openformulieren.submission_action(
        http, submission, "_complete", openformulieren.COMPLETE, {}, timeout=60
    )
    assert (response.status_code, slept) == (400, [17.0])


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


def test_failed_report_download_says_what_the_web_pod_has_then_and_on_each_retry(
    fake_http, env, fake_runner, monkeypatch
):
    monkeypatch.setattr(openformulieren, "Clock", lambda: Clock(sleep=lambda _seconds: None))
    sent = fake_http({"GET /submissions/pdf/3/t/download": (404, {})})
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "openformulieren"}}]}))
    value = {"report": True, "file": "submission-reports/2026/10/15/r.pdf", "on_disk": False}
    fake_runner.answers["exec -i deploy/openformulieren"] = (0, f"PTEST_VALUE={json.dumps(value)}\n")
    status = {"submission": "s1", "reportDownloadUrl": f"{OF}/submissions/pdf/3/t/download", "doneAt": "T0"}
    with pytest.raises(AssertionError) as info:
        download_report(env, requests.Session(), status)
    lines = str(info.value).splitlines()
    assert re.fullmatch(r"report download: HTTP 404 at \S+; status done at T0", lines[0])
    assert "'on_disk': False" in lines[1]
    assert [line.split(" at ")[0].strip() for line in lines[2:]] == [f"retry +{d}s" for d in REPORT_RETRIES]
    assert len(sent) == 1 + len(REPORT_RETRIES)


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
            "GET /zaken/api/v1/zaken": (200, [zaak for _ in range(found)]),
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


def test_upload_file_value_and_logic_helpers(fake_http):
    base = "https://forms.example.test"
    step = {"url": f"{base}/api/v2/submissions/s1/steps/st1"}
    upload = {"url": f"{base}/api/v2/submissions/files/f1", "name": "a.txt", "size": 3}
    sent = fake_http(
        {
            "POST /api/v2/formio/fileupload": (200, upload),
            "POST /api/v2/submissions/s1/steps/st1/_check-logic": (200, {"step": {"canSubmit": False}}),
            "PUT /api/v2/forms/u1/logic-rules": (200, []),
        }
    )
    http = requests.Session()
    response = openformulieren.upload_file(http, base, {"url": f"{base}/api/v2/submissions/s1"}, {}, "a.txt", b"abc")
    assert response.json() == upload
    assert b"submissions/s1" in sent[0].body
    value = openformulieren.file_value(base, upload)
    assert (value["url"], value["originalName"], value["data"]) == (
        upload["url"],
        "a.txt",
        {**upload, "baseUrl": base, "form": "", "project": ""},
    )
    assert openformulieren.can_submit_step(http, step, {}, {"akkoord": "nee"}) is False
    openformulieren.set_logic_rules(http, base, {"uuid": "u1"}, [{"order": 0}])
    assert json.loads(sent[-1].body) == [{"order": 0}]


def test_submission_summary_lists_label_and_value_in_order(fake_http):
    summary = [
        {"slug": "s1", "data": [{"name": "Kinderen", "value": None}, {"name": "Naam", "value": "Anna"}]},
        {"slug": "s2", "data": [{"name": "Naam", "value": "Bram"}]},
    ]
    fake_http({"GET /api/v2/submissions/s/summary": (200, summary)})
    submission = {"url": f"{OF}/api/v2/submissions/s"}
    pairs = openformulieren.submission_summary(requests.Session(), submission, {})
    assert pairs == [("Kinderen", None), ("Naam", "Anna"), ("Naam", "Bram")]


@pytest.mark.parametrize(("final", "refused"), [(f"{OF}/klacht/", False), (f"{OF}/auth/oidc/callback?error=x", True)])
def test_log_in_starts_the_forms_login_method_and_fails_on_a_refused_callback(fake_http, monkeypatch, final, refused):
    options = [{"identifier": "digid_oidc", "url": f"{OF}/auth/klacht/digid_oidc/start"}]
    fake_http({"GET /api/v2/forms/klacht": (200, {"loginOptions": options})})
    started = []

    def form_login(_http, start_url, username, password):
        started.append((start_url, username, password))
        return SimpleNamespace(url=final, status_code=400)

    monkeypatch.setattr(openformulieren, "form_login", form_login)
    if refused:
        with pytest.raises(AssertionError, match=r"login refused at .*/callback: HTTP 400"):
            openformulieren.log_in(requests.Session(), OF, "klacht", "digid_oidc", ("u", "p"))
    else:
        openformulieren.log_in(requests.Session(), OF, "klacht", "digid_oidc", ("u", "p"))
    assert started == [(f"{OF}/auth/klacht/digid_oidc/start?next={OF}/klacht/", "u", "p")]
    with pytest.raises(AssertionError, match="form klacht has no login method eherkenning_oidc"):
        openformulieren.login_url(requests.Session(), OF, "klacht", "eherkenning_oidc")


def test_make_form_sends_its_user_defined_variables(env, fake_runner):
    snippet_answers(fake_runner, None)
    variable = {"key": "v", "data_type": "array", "prefill_plugin": "communication_preferences"}
    make_form(env, ResourceRegistry("ptest-abc", keep=True), "ptest-form", [], {}, variables=[variable])
    params = fake_runner.stdins[-1] or ""
    assert '"registration": {}' in params
    assert json.dumps([variable]) in params


def test_communication_preferences_and_email_verification(fake_http):
    submission = {"id": "s1", "url": f"{OF}/api/v2/submissions/s1"}
    preferences = [{"type": "email", "options": [{"address": "a@x.invalid", "is_verified": True}], "preferred": None}]
    sent = fake_http(
        {
            "GET /api/v2/prefill/plugins/customer-interactions/communication-preferences/s1/component/p": (
                200,
                preferences,
            ),
            "POST /api/v2/submissions/email-verifications": (201, {}),
            "POST /api/v2/submissions/email-verifications/verify": (204, {}),
        }
    )
    http = requests.Session()
    assert openformulieren.communication_preferences(http, OF, submission, {}, "p") == preferences
    mails = {"b@x.invalid": "<p><strong> AB23CD </strong></p>", "c@x.invalid": "<p>no code</p>"}
    openformulieren.verify_email(http, submission, {}, ("p", "b@x.invalid"), mails.get)  # pyright: ignore[reportArgumentType]
    assert json.loads(sent[-1].body) == {
        "submission": submission["url"],
        "componentKey": "p",
        "email": "b@x.invalid",
        "code": "AB23CD",
    }
    with pytest.raises(AssertionError, match=r"no verification code in Open Formulieren's mail to c@x\.invalid"):
        openformulieren.verify_email(http, submission, {}, ("p", "c@x.invalid"), mails.get)  # pyright: ignore[reportArgumentType]


def test_logged_in_submission_logs_a_new_user_in_and_cleanup_deletes_both(fake_http, env, fake_runner, monkeypatch):
    snippet_answers(fake_runner, None)
    sent = fake_http(answers({}))
    deleted = []
    admin = SimpleNamespace(
        new_password=lambda: "pw",
        create_user=lambda username, password, attributes: f"{username}|{password}|{attributes['bsn'][0]}",
        delete_user=deleted.append,
    )
    monkeypatch.setattr(openformulieren, "for_environment", lambda _env: admin)
    logins = []
    monkeypatch.setattr(
        openformulieren, "log_in", lambda _http, base, slug, method, _user: logins.append((base, slug, method))
    )
    registry = ResourceRegistry("ptest-abc")
    _, submission, _ = openformulieren.logged_in_submission(
        env, registry, "klacht", "digid_oidc", {"bsn": ["1"]}, initialDataReference="o1"
    )
    assert (submission["id"], logins) == ("s1", [(OF, "klacht", "digid_oidc")])
    assert json.loads(sent[-1].body)["initialDataReference"] == "o1"
    assert registry.cleanup() == []
    assert len(deleted) == 1
    assert re.fullmatch(r"klacht-login-[0-9a-f]{6}\|pw\|1", deleted[0])


def test_need_opt_in_skips_unless_the_profile_allows_the_step(env_factory, profile_factory):
    needed = []
    allowed = env_factory(profile_factory(settings={"of_prefill": True}))
    openformulieren.need_opt_in(allowed, lambda *steps: needed.extend(steps), OF_PREFILL, "openformulieren-form")
    assert needed == ["openformulieren-prefill", "openformulieren-form"]
    with pytest.raises(pytest.skip.Exception, match="profile setting of_prefill is off on test-env"):
        openformulieren.need_opt_in(env_factory(profile_factory()), needed.append, OF_PREFILL)


def test_objects_token_is_what_the_snippet_finds(env_factory, profile_factory, fake_runner):
    snippet_answers(fake_runner, {"token": "t0ken"})
    env = env_factory(profile_factory(urls={"openformulieren": OF}))
    assert openformulieren.objects_token(env, "https://objecten.test/api/v2/") == "t0ken"


def test_referentielijsten_service_is_the_slug_the_snippet_finds(env_factory, profile_factory, fake_runner):
    snippet_answers(fake_runner, {"present": True, "slug": "rl"})
    env = env_factory(profile_factory(urls={"openformulieren": OF, "referentielijsten": "https://rl.test"}))
    assert openformulieren.referentielijsten_service(env) == "rl"
    assert '"api_root": "https://rl.test/api/v1/"' in (fake_runner.stdins[-1] or "")
