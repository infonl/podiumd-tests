"""Submitting an Open Formulieren form through its public API, as the form's JavaScript SDK does."""

from __future__ import annotations

import re
import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.auth.keycloak import form_login
from podiumd_tests.auth.keycloak_admin import for_environment
from podiumd_tests.bootstrap.steps import OF_REDACTEUR
from podiumd_tests.bootstrap.steps import OF_REFERENTIELIJSTEN
from podiumd_tests.bootstrap.steps import referentielijsten_api
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.responses import expect_status
from podiumd_tests.results import TAG_PREFIX
from podiumd_tests.results import now_iso
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.wait import Clock
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from podiumd_tests.bootstrap.snippet_step import SnippetStep
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


# Seconds after a failed report download to try it again, for the failure message.
REPORT_RETRIES = (2, 5, 10, 30)


def form_and_headers(http: requests.Session, base_url: str, slug: str) -> tuple[JsonObject, dict[str, str]]:
    """Return the form, and the headers the session's writes to Open Formulieren's API need."""
    form_response = expect_status(http.get(f"{base_url}/api/v2/forms/{slug}"), HTTPStatus.OK)
    # Every write echoes the CSRF token that API responses carry in this header.
    headers = {"X-CSRFToken": form_response.headers.get("X-CSRFToken", ""), "Referer": f"{base_url}/{slug}/"}
    return cast("JsonObject", form_response.json()), headers


def login_url(http: requests.Session, base_url: str, slug: str, method: str) -> str:
    """Return the URL that starts the form's login with method (digid_oidc, eherkenning_oidc) and returns to it."""
    form, _ = form_and_headers(http, base_url, slug)
    starts = {option.get("identifier"): option.get("url") for option in entries(form["loginOptions"])}
    if method not in starts:
        msg = f"form {slug} has no login method {method}"
        raise AssertionError(msg)
    return f"{starts[method]}?next={base_url}/{slug}/"


def log_in(http: requests.Session, base_url: str, slug: str, method: str, user: tuple[str, str]) -> None:
    """Log the session in on the form through Keycloak's login form (username, password), without a browser."""
    response = form_login(http, login_url(http, base_url, slug, method), *user)
    if "/callback" in response.url:
        msg = f"login refused at {response.url.split('?')[0]}: HTTP {response.status_code}"
        raise AssertionError(msg)


def new_submission(
    http: requests.Session, base_url: str, slug: str, **fields: object
) -> tuple[requests.Response, dict[str, str]]:
    """POST a new submission of the form as the session; Open Formulieren's answer and the headers writes need.

    fields: further fields of the submission, e.g. initialDataReference.
    """
    form, headers = form_and_headers(http, base_url, slug)
    body = {"form": form["url"], "formUrl": f"{base_url}/{slug}/", **fields}
    return http.post(f"{base_url}/api/v2/submissions", json=body, headers=headers), headers


def start_submission(
    http: requests.Session, base_url: str, slug: str, **fields: object
) -> tuple[JsonObject, dict[str, str]]:
    """Start a submission of the form as the session (new_submission); returns it and the headers its writes need."""
    response, headers = new_submission(http, base_url, slug, **fields)
    return _json(response, HTTPStatus.CREATED), headers


def log_in_as(
    env: Environment, registry: ResourceRegistry, slug: str, method: str, identity: Mapping[str, list[str]]
) -> requests.Session:
    """Return a session of a new Keycloak user with the identity attributes, logged in on the form.

    Cleanup deletes the user.
    """
    admin = for_environment(env)
    username, password = f"{slug}-login-{secrets.token_hex(3)}", admin.new_password()
    user_id = admin.create_user(username, password, dict(identity))
    # A fresh admin: the master realm's tokens expire within minutes.
    registry.add(f"keycloak user {username}", lambda: for_environment(env).delete_user(user_id))
    http = env.session()
    log_in(http, env.profile.urls["openformulieren"], slug, method, (username, password))
    return http


def logged_in_submission(
    env: Environment,
    registry: ResourceRegistry,
    slug: str,
    method: str,
    identity: Mapping[str, list[str]],
    **fields: object,
) -> tuple[requests.Session, JsonObject, dict[str, str]]:
    """Start a submission of the form as a new user (log_in_as); the session, the submission and its headers.

    Cleanup deletes the user and the submission.
    """
    http = log_in_as(env, registry, slug, method, identity)
    submission, headers = start_submission(http, env.profile.urls["openformulieren"], slug, **fields)
    forget_submission(env, registry, str(submission["id"]))
    return http, submission, headers


def submit(  # noqa: PLR0913  # one flow
    env: Environment,
    http: requests.Session,
    registry: ResourceRegistry,
    slug: str,
    data: Mapping[str, object],
    *,
    timeout: float,
    registers: bool = True,
) -> JsonObject:
    """Fill the single step of an anonymous form, complete it and return the final submission status.

    The status has `publicReference`: the identificatie of the zaak a ZGW registration created,
    and `submission`: the submission's uuid. Cleanup deletes the submission. With registers,
    also wait_for_registration; a form waiting for a co-signer does not register yet.
    """
    submission, headers = start_submission(http, env.profile.urls["openformulieren"], slug)
    forget_submission(env, registry, str(submission["id"]))
    return complete_submission(env, http, submission, headers, data, timeout=timeout, registers=registers)


def complete_submission(  # noqa: PLR0913  # one flow
    env: Environment,
    http: requests.Session,
    submission: JsonObject,
    headers: dict[str, str],
    data: Mapping[str, object],
    *,
    timeout: float,
    registers: bool = True,
) -> JsonObject:
    """Fill the submission's single step with data, complete it and return its final status (see submit)."""
    status_url = send_submission(http, submission, headers, data, timeout=timeout)
    status = submission_result(http, status_url, str(submission["id"]), timeout=timeout)
    if registers:
        wait_for_registration(env, str(submission["id"]), timeout=timeout)
    return status


def send_submission(
    http: requests.Session,
    submission: JsonObject,
    headers: dict[str, str],
    data: Mapping[str, object],
    *,
    timeout: float,
) -> str:
    """Fill the submission's single step with data and complete it; return the URL of its processing status."""
    expect_status(save_step(http, submission, headers, data), HTTPStatus.CREATED, HTTPStatus.OK)
    completed = submission_action(http, submission, "_complete", COMPLETE, headers, timeout=timeout)
    return str(_json(completed, HTTPStatus.OK)["statusUrl"])


def submission_result(http: requests.Session, status_url: str, submission: str, *, timeout: float) -> JsonObject:
    """Return the final status of a completed submission, with its uuid as `submission`."""
    return {**_processed(http, status_url, submission, timeout=timeout), "submission": submission}


def save_step(
    http: requests.Session, submission: JsonObject, headers: dict[str, str], data: Mapping[str, object]
) -> requests.Response:
    """Save data in the submission's single step, as Volgende does; Open Formulieren's answer.

    Saving checks the data's form (a repeating group's maximum of rows); required fields wait for _complete.
    """
    step = entries(submission["steps"])[0]
    return http.put(str(step["url"]), json={"data": dict(data)}, headers=headers)


def submission_summary(
    http: requests.Session, submission: JsonObject, headers: dict[str, str]
) -> list[tuple[str, object]]:
    """Return the (label, value) pairs of the submission's overview page in order; a group row is a label."""
    response = http.get(f"{submission['url']}/summary", headers=headers)
    fields = [
        field for step in entries(expect_status(response, HTTPStatus.OK).json()) for field in entries(step["data"])
    ]
    return [(str(field["name"]), field.get("value")) for field in fields]


def communication_preferences(
    http: requests.Session, base_url: str, submission: JsonObject, headers: dict[str, str], component: str
) -> list[JsonObject]:
    """Return the addresses a customerProfile component offers: per type its options and the preferred one."""
    url = (
        f"{base_url}/api/v2/prefill/plugins/customer-interactions/communication-preferences/"
        f"{submission['id']}/component/{component}"
    )
    return entries(expect_status(http.get(url, headers=headers), HTTPStatus.OK).json())


# The code in Open Formulieren's verification mail (template emails/email_verification/request.html).
VERIFICATION_CODE = re.compile(r"<strong>\s*([A-Z2-9]{6})\s*</strong>")


def verify_email(
    http: requests.Session,
    submission: JsonObject,
    headers: dict[str, str],
    field: tuple[str, str],
    read_mail: Callable[[str], str],
) -> None:
    """Verify the e-mail address of the submission's field (component key, address) with the code it is mailed.

    read_mail returns the HTML of the first mail to an address.
    """
    component, email = field
    body = {"submission": submission["url"], "componentKey": component, "email": email}
    base_url = str(submission["url"]).split("/api/v2/", maxsplit=1)[0]
    verifications = f"{base_url}/api/v2/submissions/email-verifications"
    expect_status(http.post(verifications, json=body, headers=headers), HTTPStatus.CREATED)
    mail = read_mail(email)
    code = VERIFICATION_CODE.search(mail)
    if code is None:
        msg = f"no verification code in Open Formulieren's mail to {email}: {mail[:300]}"
        raise AssertionError(msg)
    verified = http.post(f"{verifications}/verify", json={**body, "code": code[1]}, headers=headers)
    expect_status(verified, HTTPStatus.OK, HTTPStatus.NO_CONTENT)


# The body of _complete, as Verzenden sends it.
COMPLETE = {"privacyPolicyAccepted": True}
# Seconds to wait after a 429 without Retry-After.
THROTTLE_WAIT = 2.0


def submission_action(  # noqa: PLR0913  # the action, its body and the session's headers
    http: requests.Session,
    submission: JsonObject,
    action: str,
    body: Mapping[str, object],
    headers: dict[str, str],
    *,
    timeout: float,
) -> requests.Response:
    """POST the submission's _complete or _suspend; Open Formulieren's answer once it is not 429.

    Open Formulieren throttles both per client address (OPEN_FORMS_API_SUBMIT_RATE_LIMIT 10/minute and
    OPEN_FORMS_API_PAUSE_RATE_LIMIT 3/minute by default), which parallel test workers exceed; its 429 says in
    Retry-After when to try again.
    """
    url = f"{submission['url']}/{action}"
    retry_after = [THROTTLE_WAIT]

    def attempt() -> tuple[requests.Response] | None:
        response = http.post(url, json=dict(body), headers=headers)
        if response.status_code != HTTPStatus.TOO_MANY_REQUESTS:
            # In a tuple: a Response is falsy for any error status, which wait_until would retry.
            return (response,)
        retry_after[0] = float(response.headers.get("Retry-After", THROTTLE_WAIT))
        return None

    return wait_until(attempt, timeout=timeout, interval=lambda: retry_after[0], description=f"{url} not throttled")[0]


def wait_for_registration(env: Environment, submission: str, *, timeout: float) -> None:
    """Wait for Open Formulieren's own registration status of the submission; AssertionError when it failed.

    The public status reports success before the registration has finished, also when it fails.
    """

    def finished() -> dict[str, str] | None:
        result = registration_state(env, submission)
        return result if result["status"] in {"success", "failed"} else None

    result = wait_until(finished, timeout=timeout, description=f"registration of submission {submission}")
    if result["status"] == "failed":
        msg = f"registration of submission {submission} failed: {result['error']}"
        raise AssertionError(msg)


def download_report(env: Environment, http: requests.Session, status: JsonObject) -> bytes:
    """Return the submission's PDF report through the inwoner's download link.

    A failed download fails the test, after retries that record when the web pod serves the file
    (a 404 although the worker wrote it: NFS cache or another test's same-named report).
    """
    url, first = str(status["reportDownloadUrl"]), now_iso("milliseconds")
    response = http.get(url)
    if response.status_code == HTTPStatus.OK:
        return response.content
    lines = [
        f"report download: HTTP {response.status_code} at {first}; status done at {status.get('doneAt')}",
        f"  web pod at {now_iso('milliseconds')}: {_report_state(env, status)}",
    ]
    clock = Clock()
    start = clock.now()
    for delay in REPORT_RETRIES:
        clock.sleep(max(0, start + delay - clock.now()))
        at, code = now_iso("milliseconds"), http.get(url).status_code
        lines.append(f"  retry +{delay}s at {at}: HTTP {code}; web pod: {_report_state(env, status)}")
        if code == HTTPStatus.OK:
            break
    raise AssertionError("\n".join(lines))


def _report_state(env: Environment, status: JsonObject) -> object:
    params: dict[str, object] = {"uuid": str(status["submission"]), "action": "report"}
    return run_snippet(env.kube, env.deployment_for("openformulieren"), "openformulieren_submission", params)


def registration_state(env: Environment, submission: str) -> dict[str, str]:
    """Open Formulieren's registration status of the submission (pending, in_progress, success, failed) and error."""
    params: dict[str, object] = {"uuid": submission, "action": "registration"}
    deployment = env.deployment_for("openformulieren")
    return cast("dict[str, str]", run_snippet(env.kube, deployment, "openformulieren_submission", params))


def _processed(http: requests.Session, status_url: str, submission: str, *, timeout: float) -> JsonObject:
    """Return the submission's public status once Open Formulieren processed it; AssertionError when that failed."""

    def finished() -> JsonObject | None:
        status = _json(http.get(status_url), HTTPStatus.OK)
        return status if status.get("status") in {"done", "failed"} else None

    status = wait_until(finished, timeout=timeout, description=f"submission {submission} done")
    status = {**status, "doneAt": now_iso("milliseconds")}
    if status.get("status") == "failed":
        msg = f"submission {submission} failed: {status.get('errorMessage')}"
        raise AssertionError(msg)
    # "done" also covers a failed registration, which leaves publicReference empty.
    if status.get("result") != "success" or not status.get("publicReference"):
        msg = f"submission {submission}: result {status.get('result')!r}, {status.get('errorMessage')!r}"
        raise AssertionError(msg)
    return status


def registered_zaak(
    env: Environment, openzaak: ApiClient, registry: ResourceRegistry, status: JsonObject
) -> JsonObject:
    """Return the zaak a submission registered; cleanup deletes the submission, then the zaak.

    Open Zaak reissues a deleted zaak's identificatie, and Open Formulieren refuses to register a
    zaak whose identificatie a remaining submission holds as public reference: in the reverse
    order a parallel registration fails.
    """
    submission = str(status["submission"])
    zaken = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": str(status["publicReference"])})

    def delete() -> None:
        for zaak in zaken:
            delete_zaak(openzaak, str(zaak["url"]), with_documents=True)

    registry.add(f"zaken of submission {submission}", delete)
    forget_submission(env, registry, submission)  # LIFO: before the zaken
    if len(zaken) != 1:
        msg = f"submission {submission}: {len(zaken)} zaken with identificatie {status['publicReference']}"
        raise AssertionError(msg)
    return zaken[0]


def make_form(  # noqa: PLR0913, PLR0917  # mirrors the snippet's parameters
    env: Environment,
    registry: ResourceRegistry,
    slug: str,
    components: Sequence[Mapping[str, object]],
    registration: Mapping[str, object],
    auth_backends: tuple[str, ...] = (),
    payment: Mapping[str, object] | None = None,
    variables: Sequence[Mapping[str, object]] = (),
    **settings: object,
) -> None:
    """Create a one-step test form (snippet openformulieren_form) that cleanup deletes with its submissions.

    registration: {} for none. payment: {"backend", "merchant", "price"} for a form that asks for a payment.
    variables: user-defined form variables, e.g. one a prefill plugin fills.
    """
    deployment = env.deployment_for("openformulieren")
    params: dict[str, object] = {
        "slug": slug,
        "components": [dict(component) for component in components],
        "registration": dict(registration),
        "variables": [dict(variable) for variable in variables],
        "auth_backends": list(auth_backends),
        "payment": dict(payment or {}),
    }
    run_snippet(env.kube, deployment, "openformulieren_form", {**params, "settings": settings, "action": "apply"})
    registry.add_snippet(f"form {slug}", env.kube, deployment, "openformulieren_form", _removal(slug))


def remove_form(env: Environment, slug: str) -> None:
    """Delete a test form with its step, product and submissions."""
    run_snippet(env.kube, env.deployment_for("openformulieren"), "openformulieren_form", _removal(slug))


def _removal(slug: str) -> dict[str, object]:
    """Parameters of snippet openformulieren_form that delete the form."""
    return {"slug": slug, "action": "remove"}


def tagged_forms(env: Environment) -> list[str]:
    """Return the slugs of the forms, steps and products whose name starts with ptest-, bootstrap ones included."""
    params: dict[str, object] = {"prefix": TAG_PREFIX, "action": "list"}
    found = run_snippet(env.kube, env.deployment_for("openformulieren"), "openformulieren_form", params)
    return [str(slug) for slug in cast("list[object]", found)]


def upload_file(  # noqa: PLR0913, PLR0917  # one upload
    http: requests.Session, base_url: str, submission: JsonObject, headers: dict[str, str], name: str, content: bytes
) -> requests.Response:
    """Upload a file for a submission, as the form's file field does; the temporary upload's response."""
    files = {"file": (name, content, "text/plain")}
    data = {"submission": str(submission["url"])}
    return http.post(f"{base_url}/api/v2/formio/fileupload", files=files, data=data, headers=headers)


def file_value(base_url: str, upload: JsonObject, content_type: str = "text/plain") -> dict[str, object]:
    """Return the value of a Form.io file field that holds one temporary upload."""
    reference = {"url": upload["url"], "name": upload["name"], "size": upload["size"]}
    return {
        **reference,
        "storage": "url",
        "originalName": upload["name"],
        "type": content_type,
        "data": {**reference, "baseUrl": base_url, "form": "", "project": ""},
    }


def can_submit_step(
    http: requests.Session, step: JsonObject, headers: dict[str, str], data: Mapping[str, object]
) -> bool:
    """Return whether the form's logic lets the step with this data go on (its Volgende button)."""
    response = http.post(f"{step['url']}/_check-logic", json={"data": dict(data)}, headers=headers)
    return bool(section(_json(response, HTTPStatus.OK), "step")["canSubmit"])


def set_logic_rules(editor: requests.Session, base_url: str, form: JsonObject, rules: Sequence[JsonObject]) -> None:
    """Replace the form's logic rules, as the form designer saves them."""
    response = editor.put(f"{base_url}/api/v2/forms/{form['uuid']}/logic-rules", json=[dict(rule) for rule in rules])
    expect_status(response, HTTPStatus.OK)


def need_opt_in(env: Environment, need_bootstrap: Callable[..., None], step: SnippetStep, *also: str) -> None:
    """Skip where the profile does not allow the opt-in bootstrap step; else need it and the steps also."""
    if not env.profile.is_allowed(str(step.opt_in)):
        pytest.skip(
            f"profile setting {step.opt_in} is off on {env.profile.name}: set it and run bootstrap step {step.name}"
        )
    need_bootstrap(step.name, *also)


def referentielijsten_service(env: Environment) -> str:
    """Return the slug of Open Formulieren's service for Referentielijsten (bootstrap step OF_REFERENTIELIJSTEN)."""
    params = {**OF_REFERENTIELIJSTEN.params, "api_root": referentielijsten_api(env), "action": "status"}
    found = run_snippet(env.kube, env.deployment_for("openformulieren"), OF_REFERENTIELIJSTEN.snippet, params)
    return str(cast("dict[str, object]", found)["slug"])


def objects_token(env: Environment, api_root: str) -> str:
    """Return the Objecten token of Open Formulieren's Objects API group on the API root; "" when it has none."""
    found = run_snippet(
        env.kube, env.deployment_for("openformulieren"), "openformulieren_objects_token", {"api_root": api_root}
    )
    return str(cast("dict[str, object]", found)["token"])


def redacteur_session(env: Environment) -> requests.Session:
    """Return a session on Open Formulieren's API as the test form editor (bootstrap OF_REDACTEUR), by its API token."""
    http = env.session()
    http.headers["Authorization"] = f"Token {env.credentials.get(str(OF_REDACTEUR.store_key))}"
    return http


def forget_submission(env: Environment, registry: ResourceRegistry, uuid: str) -> None:
    """Cleanup deletes the submission, so its public reference cannot block a later registration."""
    params: dict[str, object] = {"uuid": uuid, "action": "delete"}
    deployment = env.deployment_for("openformulieren")
    registry.add_snippet(f"submission {uuid}", env.kube, deployment, "openformulieren_submission", params)


def _json(response: requests.Response, *expected: int) -> JsonObject:
    return cast("JsonObject", expect_status(response, *expected).json())
