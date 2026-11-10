"""Open Inwoner without a login: homepage, contact form, unknown pages and the zaken webhook.

Ported from TA regression 83, 110 (contact part) and 65a/b; the search is test_portaal_zoeken.py.
"""

from __future__ import annotations

import re

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

pytestmark = [pytest.mark.component, pytest.mark.requires("openinwoner")]

TITLE = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)


def title(html: str) -> str:
    """The page's <title>."""
    found = TITLE.search(html)
    return found.group(1).strip() if found else ""


@pytest.mark.source(
    "TA regression/83-portaal-anonieme-pagina-bereikbaarheid.spec.ts",
    "The welkom homepage is reachable for an anonymous user.",
)
@pytest.mark.source(
    "TA smoke/04-portaal-homepage.spec.ts", "The portal homepage loads without errors and renders Dutch content."
)
@pytest.mark.scenario("""
    Given a visitor who is not logged in
    When the visitor opens the homepage of Open Inwoner
    Then the portal's themed welkom page is shown
""")
def test_homepage_is_the_portal(
    http: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The homepage is the themed portal's welkom page (TA reg-83)."""
    need_bootstrap("openinwoner-cms-pages")
    html = expect_status(http.get(f"{urls['openinwoner']}/"), HTTPStatus.OK).text
    assert "openinwoner-theme" in html
    assert re.search("welkom|podiumd", title(html), re.IGNORECASE), title(html)


@pytest.mark.source(
    "TA regression/83-portaal-anonieme-pagina-bereikbaarheid.spec.ts",
    "A page that does not exist answers 404, not 500.",
)
@pytest.mark.scenario("""
    Given a visitor who is not logged in
    When the visitor opens a page that does not exist in Open Inwoner
    Then the portal answers page not found, not an error
""")
def test_unknown_page_is_404(http: requests.Session, urls: dict[str, str]) -> None:
    """An unknown CMS path answers 404, not an error (TA reg-83)."""
    expect_status(http.get(f"{urls['openinwoner']}/pages/ptest-bestaat-niet/"), HTTPStatus.NOT_FOUND)


@pytest.mark.source(
    "TA regression/110-portaal-anoniem-en-mobile.spec.ts",
    "A user who is not logged in can submit a contact request on /contactformulier/.",
)
@pytest.mark.scenario("""
    Given a visitor who is not logged in
    When the visitor opens the contactformulier in Open Inwoner
    Then the page shows the Contactformulier heading
    And the form has the subject and question fields
""")
def test_contact_form_is_open_to_everyone(
    http: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The contact form page shows a form without a login (TA reg-110)."""
    need_bootstrap("openinwoner-cms-pages")
    html = expect_status(http.get(f"{urls['openinwoner']}/contactformulier/"), HTTPStatus.OK).text
    # The contact form page has an empty <title> (also in TA); its heading names it.
    assert re.search(r"<h1[^>]*>\s*Contactformulier", html), "no Contactformulier heading"
    # The fields, not just the form: without its apphook the page renders empty field labels.
    for field in ('name="subject"', 'name="question"'):
        assert field in html, f"contact form without {field}"


@pytest.mark.parametrize("body", [{}, {"kanaal": "test"}], ids=["empty", "test-kanaal"])
@pytest.mark.source(
    "TA regression/65-oi-cache-webhook.spec.ts",
    "Open Inwoner's zaken notifications webhook exists and refuses calls without the subscription's auth.",
)
@pytest.mark.scenario("""
    Given a caller without the subscription's credentials
    When the caller sends a notification to Open Inwoner's zaken webhook
    Then Open Inwoner refuses it as unauthenticated
""")
def test_zaken_webhook_refuses_unauthenticated_calls(
    http: requests.Session, urls: dict[str, str], body: dict[str, str]
) -> None:
    """Open Inwoner's notifications webhook answers 401 without the subscription's auth (TA reg-65a/b)."""
    response = http.post(f"{urls['openinwoner']}/api/openzaak/notifications/webhook/zaken", json=body)
    assert expect_status(response, HTTPStatus.UNAUTHORIZED).json()["detail"] == "cannot authenticate subscription"
