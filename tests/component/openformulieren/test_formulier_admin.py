"""Open Formulieren's admin: the pages with its JavaScript bundle (the form designer) render it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from playwright.sync_api import expect

from podiumd_tests.auth.django_admin import superuser_login
from podiumd_tests.browser import share_cookies

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.ui, pytest.mark.requires("openformulieren")]

# Admin pages that load the bundle; it renders a marker element with this test id (js/components/admin/e2e-marker.js).
BUNDLE_PAGES = ("/admin/forms/form/add/", "/admin/forms/formdefinition/add/", "/admin/config/globalconfiguration/")
MARKER = "e2e-test-id"


@pytest.mark.parametrize("path", BUNDLE_PAGES)
@pytest.mark.source(
    "upstream open-formulieren/open-forms src/openforms/tests/e2e/test_admin_js.py",
    "Admin pages that include the Webpack admin JS bundle do not crash: the bundle renders its e2e marker.",
)
def test_admin_page_renders_its_javascript_bundle(
    page: Page, podiumd_env: Environment, credentials: SecretResolver, path: str
) -> None:
    """The superuser opens the page and the bundle's marker renders: static files, CSP and the bundle itself work."""
    http, _ = superuser_login(podiumd_env, credentials, "openformulieren")
    share_cookies(http, page)
    page.goto(podiumd_env.profile.urls["openformulieren"] + path)
    expect(page.get_by_test_id(MARKER)).to_have_count(1)
