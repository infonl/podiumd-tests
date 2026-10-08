"""The test admin's ZAC session, for the ZAC component tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KeycloakUser
from podiumd_tests.browser import redirect_login

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from playwright.sync_api import Page

    from podiumd_tests.environment import Environment

ADMIN = KeycloakUser("admin")


@pytest.fixture(name="zac")
def fixture_zac(page: Page, podiumd_env: Environment, need_bootstrap: Callable[..., None]) -> requests.Session:
    """The test admin's ZAC session."""
    need_bootstrap(ADMIN.name)
    urls = podiumd_env.profile.urls
    return redirect_login(page, podiumd_env, urls["zac"], ADMIN.username, podiumd_env.credentials.get(ADMIN.store_key))
