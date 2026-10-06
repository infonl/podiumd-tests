"""Is every component reachable through its ingress?

Ported from MK/PI test_reachability.py and TA/EX smoke 81-continuiteit-pings,
00h and 00l. Redirects are followed and only the final answer counts (R14):
ingresses differ in 301/302/303, so the status of a redirect is not asserted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.components import COMPONENTS

if TYPE_CHECKING:
    import requests

pytestmark = pytest.mark.smoke

MAX_SECONDS = 5.0

# Django apps with the standard admin login page (Open Formulieren redirects to its classic login).
DJANGO_ADMIN = (
    "openzaak",
    "openklant",
    "openformulieren",
    "openarchiefbeheer",
    "objecten",
    "objecttypen",
    "opennotificaties",
    "openinwoner",
)


def _per_component(names: tuple[str, ...] | list[str]) -> list[object]:
    return [pytest.param(n, id=n, marks=pytest.mark.requires(n)) for n in names]


@pytest.mark.parametrize("component", _per_component(sorted(COMPONENTS)))
def test_root_answers(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """The root of each component answers without a server error, within 5 s (81).

    Client errors are fine: the root of an API (Open Formulieren 403, ITA 401) need not be a page.
    """
    response = http.get(urls[component] + "/", timeout=MAX_SECONDS)
    assert response.status_code < 500, f"{response.url}: HTTP {response.status_code}"
    assert response.elapsed.total_seconds() < MAX_SECONDS


@pytest.mark.parametrize("component", _per_component(DJANGO_ADMIN))
def test_django_admin_login_page(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """The admin login page renders (MK/PI admin login reachable, 00h, 00l, 81)."""
    response = http.get(urls[component] + "/admin/login/")
    assert response.status_code == 200, f"{response.url}: HTTP {response.status_code}"
    assert "login" in response.url
