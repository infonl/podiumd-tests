"""Environment tests: they need a live environment; run them with `podiumd-tests run`."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.browser import context_args
from podiumd_tests.browser import guard_navigation
from podiumd_tests.browser import launch_args
from podiumd_tests.mailpit import own_address
from podiumd_tests.zac import afzenders

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytest_plugins = ["podiumd_tests.pytest_plugin", "podiumd_tests.ita"]


# pytest-playwright's own fixtures, extended here: a conftest overrides a plugin's fixture.
@pytest.fixture(scope="session")
def browser_type_launch_args(
    browser_type_launch_args: dict[str, object], podiumd_env: Environment
) -> dict[str, object]:
    """Chromium reaches the profile hosts as the HTTP sessions do."""
    args = [*cast("list[str]", browser_type_launch_args.get("args") or []), *launch_args(podiumd_env)]
    return {**browser_type_launch_args, "args": args}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, object], podiumd_env: Environment) -> dict[str, object]:
    """Every page starts with the profile's TLS settings, in Dutch."""
    return {**browser_context_args, **context_args(podiumd_env), "locale": "nl-NL"}


@pytest.fixture
def page(page: Page) -> Page:
    """pytest-playwright's page; a host network change does not abort its goto or reload."""
    return guard_navigation(page)


@pytest.fixture(name="zac_mail")
def fixture_zac_mail(
    zac: requests.Session, urls: dict[str, str], registry: ResourceRegistry
) -> Callable[..., JsonObject]:
    """Return a mail from the zaak to a run-tagged address, from ZAC's first afzender; fields override."""

    def build(zaak: JsonObject, **fields: object) -> JsonObject:
        return {
            "verzender": afzenders(zac, urls["zac"], zaak)[0]["mail"],
            "ontvanger": own_address(registry),
            "onderwerp": "Zaak {ZAAK_NUMMER}",
            "body": "<p>Over zaak {ZAAK_NUMMER}: {ZAAK_OMSCHRIJVING}</p>",
            "createDocumentFromMail": False,
            "vertrouwelijkheidaanduiding": "OPENBAAR",
            **fields,
        }

    return build
