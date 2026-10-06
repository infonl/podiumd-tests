"""Are the APIs up and guarded? Health endpoints answer; anonymous calls are refused.

Ported from TA/EX smoke 00j, 00k, 06, 66 (API key checks), 72 (anonymous),
79 (anonymous) and 81. A refused anonymous call shows the API is routed and
its authentication is wired, without needing any credentials.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

pytestmark = pytest.mark.smoke

HEALTH = [
    ("kiss", "/healthz"),
    ("kiss", "/api/healthcheck"),
]

# (component, method, path, extra headers)
ANONYMOUS = [
    ("openzaak", "GET", "/catalogi/api/v1/catalogussen", {}),
    ("openzaak", "GET", "/zaken/api/v1/zaken", {}),
    ("openklant", "GET", "/klantinteracties/api/v1/partijen", {}),
    ("objecten", "GET", "/api/v2/objects", {}),
    ("objecttypen", "GET", "/api/v2/objecttypes", {}),
    ("opennotificaties", "GET", "/api/v1/kanaal", {}),
    ("ita", "GET", "/api/kanalen", {}),
    ("omc", "POST", "/Events/Listen", {}),
    ("pabc", "POST", "/api/v1/application-roles-per-entity-type", {}),
    ("pabc", "POST", "/api/v1/application-roles-per-entity-type", {"X-API-KEY": "ptest-wrong-key"}),
]


@pytest.mark.parametrize(("component", "path"), [requiring(c, c, p, test_id=f"{c}{p}") for c, p in HEALTH])
def test_health_endpoint(http: requests.Session, urls: dict[str, str], component: str, path: str) -> None:
    """The component's own health endpoint reports healthy."""
    expect_status(http.get(urls[component] + path), HTTPStatus.OK)


@pytest.mark.parametrize(
    ("component", "method", "path", "headers"),
    [requiring(c, c, m, p, h, test_id=f"{c}{p}{'-wrong-key' if h else ''}") for c, m, p, h in ANONYMOUS],
)
def test_anonymous_call_is_refused(
    http: requests.Session, urls: dict[str, str], component: str, method: str, path: str, headers: dict[str, str]
) -> None:
    """Without (valid) credentials the API answers 401 or 403, not data and not a server error.

    POSTs carry a harmless body; they are refused before anything is stored.
    """
    body = ({"FunctionalRoleNames": ["ptest"]} if component == "pabc" else {}) if method == "POST" else None
    response = http.request(method, urls[component] + path, json=body, headers=headers, allow_redirects=False)
    expect_status(response, *REFUSED)
