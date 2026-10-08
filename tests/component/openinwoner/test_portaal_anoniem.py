"""Open Inwoner without a login: homepage, search, contact form, unknown pages and the zaken webhook.

Ported from TA regression 83, 107, 110 (contact part), 161c/d and 65a/b.
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


def test_homepage_is_the_portal(
    http: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The homepage is the themed portal's welkom page (TA reg-83)."""
    need_bootstrap("openinwoner-cms-pages")
    html = expect_status(http.get(urls["openinwoner"] + "/"), HTTPStatus.OK).text
    assert "openinwoner-theme" in html
    assert re.search("welkom|podiumd", title(html), re.IGNORECASE), title(html)


def test_unknown_page_is_404(http: requests.Session, urls: dict[str, str]) -> None:
    """An unknown CMS path answers 404, not an error (TA reg-83)."""
    expect_status(http.get(urls["openinwoner"] + "/pages/ptest-bestaat-niet/"), HTTPStatus.NOT_FOUND)


@pytest.mark.parametrize("query", ["informatie", "ptest-xyzzy-geen-resultaat"])
def test_search_answers(http: requests.Session, urls: dict[str, str], query: str) -> None:
    """Search answers with its form; a query without hits says so (TA int-107, reg-161c/d)."""
    html = expect_status(http.get(urls["openinwoner"] + "/search/", params={"query": query}), HTTPStatus.OK).text
    assert 'name="query"' in html
    if "geen" in query:
        assert "We konden geen zoekresultaten vinden" in html


def test_contact_form_is_open_to_everyone(
    http: requests.Session, urls: dict[str, str], need_bootstrap: Callable[..., None]
) -> None:
    """The contact form page shows a form without a login (TA reg-110)."""
    need_bootstrap("openinwoner-cms-pages")
    html = expect_status(http.get(urls["openinwoner"] + "/contactformulier/"), HTTPStatus.OK).text
    # The contact form page has an empty <title> (also in TA); its heading names it.
    assert re.search(r"<h1[^>]*>\s*Contactformulier", html), "no Contactformulier heading"
    # The fields, not just the form: without its apphook the page renders empty field labels.
    for field in ('name="subject"', 'name="question"'):
        assert field in html, f"contact form without {field}"


@pytest.mark.parametrize("body", [{}, {"kanaal": "test"}], ids=["empty", "test-kanaal"])
def test_zaken_webhook_refuses_unauthenticated_calls(
    http: requests.Session, urls: dict[str, str], body: dict[str, str]
) -> None:
    """Open Inwoner's notifications webhook answers 401 without the subscription's auth (TA reg-65a/b)."""
    response = http.post(urls["openinwoner"] + "/api/openzaak/notifications/webhook/zaken", json=body)
    assert expect_status(response, HTTPStatus.UNAUTHORIZED).json()["detail"] == "cannot authenticate subscription"
