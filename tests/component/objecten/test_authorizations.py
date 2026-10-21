"""Objecten authorization: a token's objecttype permissions bound what it may do.

A token is permitted per objecttype (snippets/token_auth.py object_types). Objecten checks the permission
before the object schema, so a create of a permitted type fails validation (400) while a create of an
unpermitted type is refused (403). This asserts that boundary with a throwaway restricted token.
"""

from __future__ import annotations

import secrets

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import ITA_OBJECTTYPES
from podiumd_tests.bootstrap.names import KISS_OBJECTTYPES
from podiumd_tests.clients.api import ApiClient
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.seed.objecten import objecttype_url

if TYPE_CHECKING:
    from collections.abc import Iterator

    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("objecten", "cluster"),
    pytest.mark.source(
        "podiumd-tests",
        "Checks that an Objecten token permitted on one objecttype is refused creating an object of another.",
    ),
]

OBJECTEN_TOKEN_MODULE = "objects.token.models"  # noqa: S105  # a module path, not a password
PERMITTED, UNPERMITTED = KISS_OBJECTTYPES[0], ITA_OBJECTTYPES[0]


@pytest.fixture(name="restricted_objecten")
def fixture_restricted_objecten(podiumd_env: Environment) -> Iterator[ApiClient]:
    """An Objecten client whose token is permitted on one objecttype only; removed afterwards."""
    deployment = podiumd_env.deployment_for("objecten")
    secret = secrets.token_hex(20)
    params = {"action": "apply", "modules": [OBJECTEN_TOKEN_MODULE], "identifier": "ptest-authz", "secret": secret}
    run_snippet(podiumd_env.kube, deployment, "token_auth", {**params, "object_types": [PERMITTED]})
    headers = {"Authorization": f"Token {secret}", "Content-Crs": "EPSG:4326", "Accept-Crs": "EPSG:4326"}
    yield ApiClient(podiumd_env.session(cookies=False), podiumd_env.profile.urls["objecten"] + "/api/v2", headers)
    run_snippet(
        podiumd_env.kube,
        deployment,
        "token_auth",
        {"action": "remove", "modules": [OBJECTEN_TOKEN_MODULE], "identifier": "ptest-authz"},
    )


def _create(client: ApiClient, type_url: str, *expected: int) -> int:
    body = {"type": type_url, "record": {"typeVersion": 1, "data": {}, "startAt": datetime.now(UTC).date().isoformat()}}
    return client.request("POST", "objects", *expected, json=body).status_code


def test_token_cannot_create_an_object_of_an_unpermitted_objecttype(
    restricted_objecten: ApiClient, podiumd_env: Environment
) -> None:
    """A token permitted on one objecttype is refused (403) creating an object of another; its own type is not."""
    unpermitted = _create(restricted_objecten, objecttype_url(podiumd_env, UNPERMITTED), HTTPStatus.FORBIDDEN)
    assert unpermitted == HTTPStatus.FORBIDDEN
    # The permitted type passes the permission check and fails only on the empty record's schema (400, not 403).
    permitted = _create(restricted_objecten, objecttype_url(podiumd_env, PERMITTED), HTTPStatus.BAD_REQUEST)
    assert permitted == HTTPStatus.BAD_REQUEST
