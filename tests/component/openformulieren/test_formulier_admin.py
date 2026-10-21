"""Open Formulieren's admin side: its JavaScript bundle renders, and its own checks find no broken forms."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

from playwright.sync_api import expect

from podiumd_tests.auth.django_admin import superuser_login
from podiumd_tests.browser import share_cookies
from podiumd_tests.django_snippets import run_snippet

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.component, pytest.mark.requires("openformulieren")]

# Admin pages that load the bundle; it renders a marker element with this test id (js/components/admin/e2e-marker.js).
BUNDLE_PAGES = ("/admin/forms/form/add/", "/admin/forms/formdefinition/add/", "/admin/config/globalconfiguration/")
MARKER = "e2e-test-id"


@pytest.mark.ui
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


@pytest.mark.requires("cluster")
@pytest.mark.source(
    "upstream open-formulieren/open-forms bin/report_component_problems.py",
    "Reports form definitions with broken components (null defaults, bad minDate, bad translations) before an upgrade.",
)
def test_open_formulieren_finds_no_broken_forms(podiumd_env: Environment) -> None:
    """Open Formulieren's bin/report_*.py checks find no broken form definitions or logic (as after an upgrade)."""
    results = run_snippet(
        podiumd_env.kube, podiumd_env.deployment_for("openformulieren"), "openformulieren_reports", {}
    )
    failed = {name: output for name, (ok, output) in cast("dict[str, list[object]]", results).items() if not ok}
    assert not failed, failed
