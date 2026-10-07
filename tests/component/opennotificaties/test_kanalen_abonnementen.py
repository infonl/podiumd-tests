"""Open Notificaties: kanalen and abonnementen validation. Ported from TA regression 53."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KANALEN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import strings
from podiumd_tests.seed.opennotificaties import CALLBACK_AUTH
from podiumd_tests.seed.opennotificaties import abonnement_body
from podiumd_tests.seed.opennotificaties import make_abonnement

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry
    from podiumd_tests.webhook import Callback

pytestmark = [pytest.mark.component, pytest.mark.requires("opennotificaties")]


@pytest.mark.parametrize("naam", sorted(KANALEN))
def test_kanaal_has_the_filters_tests_use(
    opennotificaties: ApiClient, need_bootstrap: Callable[..., None], naam: str
) -> None:
    """Each kanaal the tests publish on exists with its filters (bootstrap wiring opennotificaties-kanalen)."""
    need_bootstrap("opennotificaties-kanalen")
    found = opennotificaties.request("GET", "kanaal", 200, params={"naam": naam}).json()
    assert set(KANALEN[naam]) <= set(strings(entries(found)[0]["filters"]))


def test_kanaal_name_is_unique(opennotificaties: ApiClient) -> None:
    """A second kanaal named zaken is refused (TA reg-53a)."""
    opennotificaties.request("POST", "kanaal", 400, json={"naam": "zaken", "documentatieLink": "", "filters": []})


# Open Notificaties first calls the callback; only with a callback that refuses requests without
# auth and answers 204 with it does it get to validating kanalen and filters.
def test_abonnement_on_an_unknown_kanaal_is_refused(
    opennotificaties: ApiClient, registry: ResourceRegistry, callback: Callback
) -> None:
    """An abonnement on a kanaal that does not exist answers 400 (TA reg-53b)."""
    body = abonnement_body(callback.url, registry.tagged("geen-kanaal"), {})
    opennotificaties.request("POST", "abonnement", 400, json=body)


def test_abonnement_with_an_unknown_filter_is_refused(
    opennotificaties: ApiClient, registry: ResourceRegistry, callback: Callback
) -> None:
    """An abonnement filtering on an attribute the kanaal lacks answers 400 (TA reg-53d)."""
    body = abonnement_body(callback.url, "zaken", {"onbekend_kenmerk": registry.tagged("waarde")})
    opennotificaties.request("POST", "abonnement", 400, json=body)


def test_abonnement_calls_its_callback_with_its_auth(
    opennotificaties: ApiClient, registry: ResourceRegistry, callback: Callback
) -> None:
    """Creating an abonnement checks the callback: once without auth, once with the abonnement's auth."""
    make_abonnement(opennotificaties, registry, callback.url, "zaken", {})
    assert [entry["authorization"] for entry in callback.received()] == [None, CALLBACK_AUTH]


@pytest.mark.xfail(
    strict=True,
    reason="Open Notificaties: an unreachable callback URL makes POST /abonnement answer 500 "
    "(requests ConnectionError in nrc/api/validators.py) instead of a 400; not yet reported upstream",
)
def test_abonnement_with_an_unreachable_callback_is_refused(
    opennotificaties: ApiClient, registry: ResourceRegistry
) -> None:
    """A callback that cannot be reached is a validation error."""
    body = abonnement_body(f"https://{registry.tagged('callback')}.example.invalid/webhook", "zaken", {})
    opennotificaties.request("POST", "abonnement", 400, json=body)
