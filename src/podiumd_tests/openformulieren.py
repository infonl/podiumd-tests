"""Submitting an Open Formulieren form through its public API, as the form's JavaScript SDK does."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    import requests

    from podiumd_tests.json_data import JsonObject


def submit(http: requests.Session, base_url: str, slug: str, data: dict[str, object], *, timeout: float) -> JsonObject:
    """Fill the single step of an anonymous form, complete it and return the final submission status.

    The status has `publicReference`: the identificatie of the zaak a ZGW registration created.
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
    status_url = str(complete["statusUrl"])

    def finished() -> JsonObject | None:
        status = _json(http.get(status_url), HTTPStatus.OK)
        if status.get("status") == "failed":
            msg = f"submission {submission['id']} failed: {status.get('errorMessage')}"
            raise AssertionError(msg)
        return status if status.get("status") == "done" else None

    return wait_until(finished, timeout=timeout, description=f"submission {submission['id']} of form {slug} done")


def _json(response: requests.Response, *expected: int) -> JsonObject:
    return cast("JsonObject", expect_status(response, *expected).json())
