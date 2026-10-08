"""Submitting an Open Formulieren form through its public API, as the form's JavaScript SDK does."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def submit(http: requests.Session, base_url: str, slug: str, data: dict[str, object], *, timeout: float) -> JsonObject:
    """Fill the single step of an anonymous form, complete it and return the final submission status.

    The status has `publicReference`: the identificatie of the zaak a ZGW registration created,
    and `submission`: the submission's uuid, for delete_submission.
    """
    form_url = f"{base_url}/{slug}/"
    form_response = expect_status(http.get(f"{base_url}/api/v2/forms/{slug}"), HTTPStatus.OK)
    form = cast("JsonObject", form_response.json())
    # Every write echoes the CSRF token that API responses carry in this header.
    headers = {"X-CSRFToken": form_response.headers.get("X-CSRFToken", ""), "Referer": form_url}
    submission = _json(
        http.post(f"{base_url}/api/v2/submissions", json={"form": form["url"], "formUrl": form_url}, headers=headers),
        HTTPStatus.CREATED,
    )
    step = entries(submission["steps"])[0]
    expect_status(http.put(str(step["url"]), json={"data": data}, headers=headers), HTTPStatus.CREATED, HTTPStatus.OK)
    complete = _json(
        http.post(f"{submission['url']}/_complete", json={"privacyPolicyAccepted": True}, headers=headers),
        HTTPStatus.OK,
    )
    status = _registered(http, str(complete["statusUrl"]), str(submission["id"]), timeout=timeout)
    return {**status, "submission": submission["id"]}


def _registered(http: requests.Session, status_url: str, submission: str, *, timeout: float) -> JsonObject:
    """The submission's final status once registration succeeded; AssertionError otherwise."""

    def finished() -> JsonObject | None:
        status = _json(http.get(status_url), HTTPStatus.OK)
        if status.get("status") == "failed":
            msg = f"submission {submission} failed: {status.get('errorMessage')}"
            raise AssertionError(msg)
        return status if status.get("status") == "done" else None

    status = wait_until(finished, timeout=timeout, description=f"submission {submission} done")
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
                delete_zaak(openzaak, str(zaak["url"]))

    registry.add(f"submission {submission} and its zaak", delete)
    if len(zaken) != 1:
        msg = f"submission {submission}: {len(zaken)} zaken with identificatie {status['publicReference']}"
        raise AssertionError(msg)
    return zaken[0]


def delete_submission(env: Environment, uuid: str) -> None:
    """Delete a submission, so its public reference cannot block a later registration."""
    run_snippet(env.kube, env.deployment_for("openformulieren"), "openformulieren_submission", {"uuid": uuid})


def _json(response: requests.Response, *expected: int) -> JsonObject:
    return cast("JsonObject", expect_status(response, *expected).json())
