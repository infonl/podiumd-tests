"""Open Notificaties: kanalen and abonnementen validation. Ported from TA regression 53."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KANALEN
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import strings

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.component, pytest.mark.requires("opennotificaties")]


def abonnement(registry: ResourceRegistry, kanaal: str, filters: dict[str, str]) -> dict[str, object]:
    """An abonnement body with a callback that is never called."""
    return {
        "callbackUrl": f"https://{registry.tagged('callback')}.example.invalid/webhook",
        "auth": "Bearer ptest",
        "kanalen": [{"naam": kanaal, "filters": filters}],
    }


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


# Open Notificaties first calls the callback; without a callback that answers 204 it never gets
# to validating kanalen and filters. The webhook receiver of infra/ (phase 4) provides one.
NEEDS_CALLBACK = pytest.mark.skip(reason="needs a callback that answers 204: the webhook receiver of infra/ (phase 4)")


@NEEDS_CALLBACK
def test_abonnement_on_an_unknown_kanaal_is_refused(opennotificaties: ApiClient, registry: ResourceRegistry) -> None:
    """An abonnement on a kanaal that does not exist answers 400 (TA reg-53b)."""
    opennotificaties.request("POST", "abonnement", 400, json=abonnement(registry, registry.tagged("geen-kanaal"), {}))


@NEEDS_CALLBACK
def test_abonnement_with_an_unknown_filter_is_refused(opennotificaties: ApiClient, registry: ResourceRegistry) -> None:
    """An abonnement filtering on an attribute the kanaal lacks answers 400 (TA reg-53d)."""
    body = abonnement(registry, "zaken", {"onbekend_kenmerk": "waarde"})
    opennotificaties.request("POST", "abonnement", 400, json=body)


@pytest.mark.xfail(
    strict=True,
    reason="Open Notificaties: an unreachable callback URL makes POST /abonnement answer 500 "
    "(requests ConnectionError in nrc/api/validators.py) instead of a 400; not yet reported upstream",
)
def test_abonnement_with_an_unreachable_callback_is_refused(
    opennotificaties: ApiClient, registry: ResourceRegistry
) -> None:
    """A callback that cannot be reached is a validation error."""
    opennotificaties.request("POST", "abonnement", 400, json=abonnement(registry, "zaken", {}))
