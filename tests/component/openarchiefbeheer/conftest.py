"""Fixtures for Open Archiefbeheer: a session per role, its API root and a closed zaak in its cache."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.oab import API
from podiumd_tests.oab import cache_for_test
from podiumd_tests.oab import due_date
from podiumd_tests.oab import login
from podiumd_tests.oab import set_config
from podiumd_tests.seed.openzaak import close_zaak
from podiumd_tests.seed.openzaak import make_zaak

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry


@pytest.fixture(name="oab")
def fixture_oab(podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> Callable[[str], requests.Session]:
    """A logged-in session per role, made once per test."""
    sessions: dict[str, requests.Session] = {}

    def session(role: str) -> requests.Session:
        if role not in sessions:
            need_bootstrap(f"openarchiefbeheer-user-{role}")
            sessions[role] = login(podiumd_env, role)
        return sessions[role]

    return session


@pytest.fixture(name="api")
def fixture_api(urls: dict[str, str]) -> str:
    """OAB's API root."""
    return urls["openarchiefbeheer"] + API


@pytest.fixture(name="closed_zaak")
def fixture_closed_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> Callable[[], JsonObject]:
    """Makes a zaak of the test that ended two days ago with archiefnominatie vernietigen, in OAB's zaken cache.

    Its archiefactiedatum is yesterday, not ten years ahead: queue_destruction accepts it.
    """
    if not parts.resultaattypen:
        pytest.skip("test zaaktype has no resultaattype (Selectielijst API was unreachable at bootstrap)")
    return lambda: _closed_zaak(podiumd_env, openzaak, registry, parts)


@pytest.fixture(name="zaak")
def fixture_zaak(closed_zaak: Callable[[], JsonObject]) -> JsonObject:
    """One closed zaak of the test, in OAB's zaken cache."""
    return closed_zaak()


def _closed_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, parts: ZaaktypeParts
) -> JsonObject:
    gezet = datetime.now(UTC) - timedelta(days=2)
    zaak = close_zaak(openzaak, make_zaak(openzaak, registry, parts.zaaktype), parts, gezet)
    zaak = openzaak.request("PATCH", str(zaak["url"]), HTTPStatus.OK, json={"archiefactiedatum": due_date()}).json()
    cache_for_test(podiumd_env, registry, [str(zaak["url"])])
    return zaak


@pytest.fixture(name="oab_config")
def fixture_oab_config(podiumd_env: Environment) -> Iterator[Callable[..., None]]:
    """set(model, **fields): change OAB's global ArchiveConfig or EmailConfig for this test; the old values come back."""
    old: dict[str, dict[str, object]] = {}

    def change(model: str, **fields: object) -> None:
        for field, value in set_config(podiumd_env, model, fields).items():
            old.setdefault(model, {}).setdefault(field, value)

    yield change
    for model, fields in old.items():
        set_config(podiumd_env, model, fields)
