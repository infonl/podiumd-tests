"""Are the APIs up and guarded? Health endpoints answer; anonymous calls are refused.

Ported from TA/EX smoke 00j, 00k, 06, 66 (API key checks), 72 (anonymous),
79 and 81. A refused anonymous call shows the API is routed and
its authentication is wired, without needing any credentials.
"""

from __future__ import annotations

import time

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = pytest.mark.smoke

HEALTH = [
    ("kiss", "/healthz"),
    ("kiss", "/api/healthcheck"),
    ("openvtb", "/_healthz/"),
    ("zaakbrug", "/iaf/api/server/health"),
    ("zgw-office-addin", "/health"),
    ("zgw-office-addin", "/proxy/health"),
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
    ("openvtb", "GET", "/verzoeken/api/v1/verzoeken", {}),
    ("openvtb", "GET", "/taken/api/v1/externetaken", {}),
    ("openvtb", "GET", "/berichten/api/v1/berichten", {}),
    ("zgw-office-addin", "GET", "/proxy/zaken/ptest-unknown", {}),
    ("pabc", "POST", "/api/v1/application-roles-per-entity-type", {}),
    ("pabc", "POST", "/api/v1/application-roles-per-entity-type", {"X-API-KEY": "ptest-wrong-key"}),
]


@pytest.mark.source(
    "TA smoke/06-kiss-bff-healthz.spec.ts",
    "KISS BFF smoke test: /healthz returns 200, a precondition for every KISS case.",
)
@pytest.mark.source(
    "EX tests/smoke/06-kiss-bff-healthz.spec.ts",
    "KISS BFF smoke test: /healthz returns 200, a precondition for every KISS case.",
)
@pytest.mark.source(
    "TA smoke/00-environment-preflight.spec.ts",
    "Preflight that detects dead infrastructure; 00j checks the KISS frontend is reachable and its healthcheck OK.",
)
@pytest.mark.source(
    "EX tests/smoke/00-environment-preflight.spec.ts",
    "Preflight that detects dead infrastructure; 00j checks the KISS frontend is reachable and its healthcheck OK.",
)
@pytest.mark.source(
    "MK test_kiss_ita.py",
    "KISS and ITA: health, unauthenticated API and their objecttypes.",
)
@pytest.mark.source(
    "podiumd-tests",
    "PodiumD 4.10 adds Open VTB, ZaakBrug and the ZGW Office add-in, whose health endpoints are checked.",
)
@pytest.mark.parametrize(("component", "path"), [requiring(c, c, p, test_id=f"{c}{p}") for c, p in HEALTH])
def test_health_endpoint(http: requests.Session, urls: dict[str, str], component: str, path: str) -> None:
    """The component's own health endpoint reports healthy."""
    expect_status(http.get(urls[component] + path), HTTPStatus.OK)


@pytest.mark.source(
    "TA smoke/66-pabc-health.spec.ts",
    "PABC health and auth enforcement: PABC refuses a request without or with a wrong X-API-KEY (fail-closed).",
)
@pytest.mark.source(
    "EX tests/smoke/66-pabc-health.spec.ts",
    "PABC health and auth enforcement: PABC refuses a request without or with a wrong X-API-KEY (fail-closed).",
)
@pytest.mark.source(
    "TA smoke/72-ita-health-kanalen.spec.ts",
    "ITA health and kanalen endpoint: ITA refuses a request without a logged-in session.",
)
@pytest.mark.source(
    "EX tests/smoke/72-ita-health-kanalen.spec.ts",
    "ITA health and kanalen endpoint: ITA refuses a request without a logged-in session.",
)
@pytest.mark.source(
    "TA smoke/79-omc-health.spec.ts",
    "NotifyNL OMC health and auth: OMC refuses /Events/Listen without a valid token.",
)
@pytest.mark.source(
    "EX tests/smoke/79-omc-health.spec.ts",
    "NotifyNL OMC health and auth: OMC refuses /Events/Listen without a valid token.",
)
@pytest.mark.source(
    "TA smoke/00-environment-preflight.spec.ts",
    "Preflight that detects dead infrastructure; 00k checks the OK2 Klantinteracties API is reachable.",
)
@pytest.mark.source(
    "EX tests/smoke/00-environment-preflight.spec.ts",
    "Preflight that detects dead infrastructure; 00k checks the OK2 Klantinteracties API is reachable.",
)
@pytest.mark.source(
    "MK test_kiss_ita.py",
    "KISS and ITA: health, unauthenticated API and their objecttypes.",
)
@pytest.mark.source(
    "MK test_omc.py",
    "OMC as ExternalsPodiumD's smoke test 79-omc-health checks it: /Events/Listen requires a token.",
)
@pytest.mark.source(
    "podiumd-tests",
    "PodiumD 4.10 adds Open VTB and the ZGW Office add-in, whose APIs must refuse anonymous calls.",
)
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


@pytest.mark.requires("omc", "cluster")
@pytest.mark.source("TA smoke/79-omc-health.spec.ts", "NotifyNL OMC health and auth: OMC's Version endpoint answers.")
@pytest.mark.source(
    "EX tests/smoke/79-omc-health.spec.ts", "NotifyNL OMC health and auth: OMC's Version endpoint answers."
)
def test_omc_version_answers_to_its_token(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str]
) -> None:
    """OMC answers /Events/Version to a token from its own JWT settings and secret omc_jwt_secret."""
    token = omc_token(podiumd_env, time.time())
    expect_status(
        http.get(urls["omc"] + "/Events/Version", headers={"Authorization": f"Bearer {token}"}), HTTPStatus.OK
    )
