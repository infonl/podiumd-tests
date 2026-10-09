"""Submitting an Open Formulieren form through its public API, as the form's JavaScript SDK does."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_documents_of
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def start_submission(http: requests.Session, base_url: str, slug: str) -> tuple[JsonObject, dict[str, str]]:
    """Start an anonymous submission of the form; returns it and the headers its writes need."""
    form_url = f"{base_url}/{slug}/"
    form_response = expect_status(http.get(f"{base_url}/api/v2/forms/{slug}"), HTTPStatus.OK)
    form = cast("JsonObject", form_response.json())
    # Every write echoes the CSRF token that API responses carry in this header.
    headers = {"X-CSRFToken": form_response.headers.get("X-CSRFToken", ""), "Referer": form_url}
    submission = _json(
        http.post(f"{base_url}/api/v2/submissions", json={"form": form["url"], "formUrl": form_url}, headers=headers),
        HTTPStatus.CREATED,
    )
    return submission, headers


def submit(  # pylint: disable=too-many-arguments  # one flow
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
    base_url = env.profile.urls["openformulieren"]
    submission, headers = start_submission(http, base_url, slug)
    registry.add(f"submission {submission['id']}", lambda: delete_submission(env, str(submission["id"])))
    step = entries(submission["steps"])[0]
    expect_status(
        http.put(str(step["url"]), json={"data": dict(data)}, headers=headers), HTTPStatus.CREATED, HTTPStatus.OK
    )
    complete = _json(
        http.post(f"{submission['url']}/_complete", json={"privacyPolicyAccepted": True}, headers=headers),
        HTTPStatus.OK,
    )
    status = _processed(http, str(complete["statusUrl"]), str(submission["id"]), timeout=timeout)
    if registers:
        wait_for_registration(env, str(submission["id"]), timeout=timeout)
    return {**status, "submission": submission["id"]}


def wait_for_registration(env: Environment, submission: str, *, timeout: float) -> None:
    """Wait for Open Formulieren's own registration status of the submission; AssertionError when it failed.

    The public status reports success before the registration has finished, also when it fails.
    """
    deployment = env.deployment_for("openformulieren")
    params: dict[str, object] = {"uuid": submission, "action": "registration"}

    def finished() -> dict[str, str] | None:
        result = cast("dict[str, str]", run_snippet(env.kube, deployment, "openformulieren_submission", params))
        return result if result["status"] in {"success", "failed"} else None

    result = wait_until(finished, timeout=timeout, description=f"registration of submission {submission}")
    if result["status"] == "failed":
        msg = f"registration of submission {submission} failed: {result['error']}"
        raise AssertionError(msg)


def _processed(http: requests.Session, status_url: str, submission: str, *, timeout: float) -> JsonObject:
    """The submission's public status once Open Formulieren processed it; AssertionError when that failed."""

    def finished() -> JsonObject | None:
        status = _json(http.get(status_url), HTTPStatus.OK)
        return status if status.get("status") in {"done", "failed"} else None

    status = wait_until(finished, timeout=timeout, description=f"submission {submission} done")
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
    """The zaak a submission registered; cleanup deletes the submission, then the zaak.

    Open Zaak reissues a deleted zaak's identificatie, and Open Formulieren refuses to register a
    zaak whose identificatie a remaining submission holds as public reference: in the reverse
    order a parallel registration fails.
    """
    submission = str(status["submission"])
    zaken = openzaak.list(f"{ZAKEN}/zaken", {"identificatie": str(status["publicReference"])})

    def delete() -> None:
        try:
            delete_submission(env, submission)
        finally:
            for zaak in zaken:
                # Open Zaak keeps a deleted zaak's documents: the form's PDF and attachments.
                delete_documents_of(openzaak, str(zaak["url"]))
                delete_zaak(openzaak, str(zaak["url"]))

    registry.add(f"submission {submission} and its zaak", delete)
    if len(zaken) != 1:
        msg = f"submission {submission}: {len(zaken)} zaken with identificatie {status['publicReference']}"
        raise AssertionError(msg)
    return zaken[0]


def make_form(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # mirrors the snippet's parameters
    env: Environment,
    registry: ResourceRegistry,
    slug: str,
    components: Sequence[Mapping[str, object]],
    registration: Mapping[str, object],
    auth_backends: tuple[str, ...] = (),
    **settings: object,
) -> None:
    """A one-step test form (snippet openformulieren_form) that cleanup deletes with its submissions."""
    deployment = env.deployment_for("openformulieren")
    params: dict[str, object] = {
        "slug": slug,
        "components": [dict(c) for c in components],
        "registration": dict(registration),
        "auth_backends": list(auth_backends),
    }
    run_snippet(env.kube, deployment, "openformulieren_form", {**params, "settings": settings, "action": "apply"})
    registry.add(
        f"form {slug}",
        lambda: run_snippet(
            env.kube, deployment, "openformulieren_form", {**params, "settings": {}, "action": "remove"}
        ),
    )


def delete_submission(env: Environment, uuid: str) -> None:
    """Delete a submission, so its public reference cannot block a later registration."""
    params: dict[str, object] = {"uuid": uuid, "action": "delete"}
    run_snippet(env.kube, env.deployment_for("openformulieren"), "openformulieren_submission", params)


def _json(response: requests.Response, *expected: int) -> JsonObject:
    return cast("JsonObject", expect_status(response, *expected).json())
