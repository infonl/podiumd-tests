"""Referentielijsten: a read-only API of tabellen and their items, open to everyone."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("referentielijsten")]


def test_api_cannot_be_written(http: requests.Session, urls: dict[str, str]) -> None:
    """Tabellen are maintained in the admin: the API refuses a new tabel."""
    response = http.post(urls["referentielijsten"] + "/api/v1/tabellen", json={"code": "ptest", "naam": "ptest"})
    assert response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN, HTTPStatus.METHOD_NOT_ALLOWED}, (
        describe(response)
    )


@pytest.mark.requires("cluster")
def test_items_of_a_tabel_are_listed(
    http: requests.Session, urls: dict[str, str], podiumd_env: Environment, registry: ResourceRegistry
) -> None:
    """A tabel made in the admin (here: through Django) shows in the API with exactly its items."""
    deployment = podiumd_env.deployment_for("referentielijsten")
    code = registry.tagged("tabel")
    items = [{"code": "ja", "naam": "Ja"}, {"code": "nee", "naam": "Nee"}]
    params: dict[str, object] = {"action": "create", "code": code, "naam": code, "items": items}
    registry.add(
        f"tabel {code}",
        lambda: run_snippet(
            podiumd_env.kube, deployment, "referentielijsten_tabel", {"action": "delete", "code": code}
        ),
    )
    run_snippet(podiumd_env.kube, deployment, "referentielijsten_tabel", params)
    api = urls["referentielijsten"] + "/api/v1"
    tabellen = expect_status(http.get(api + "/tabellen", params={"code": code}), HTTPStatus.OK).json()
    assert code in {t.get("code") for t in entries(tabellen.get("results"))}
    found = expect_status(http.get(api + "/items", params={"tabel__code": code}), HTTPStatus.OK).json()
    assert sorted((i["code"], i["naam"]) for i in entries(found.get("results"))) == [("ja", "Ja"), ("nee", "Nee")]
