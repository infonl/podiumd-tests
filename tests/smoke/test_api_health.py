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

from podiumd_tests.bootstrap.omc import notify_mock_missing
from podiumd_tests.bootstrap.omc import omc_token
from podiumd_tests.pytest_plugin import requiring
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status
from podiumd_tests.zgw_services import VIEW_CONFIG_APPS
from podiumd_tests.zgw_services import view_config_problems

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
    ("kiss-adapter", "/healthz"),
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
    # The podiumd-adapter's routes for KISS (its AuthTests).
    ("kiss-adapter", "GET", "/contactmomenten/api/v1/contactmomenten", {}),
    ("kiss-adapter", "GET", "/contactmomenten/api/v1/klantcontactmomenten", {}),
    ("kiss-adapter", "GET", "/contactmomenten/api/v1/objectcontactmomenten", {}),
    ("kiss-adapter", "GET", "/klanten/api/v1/klanten", {}),
    ("kiss-adapter", "GET", "/zaken/api/v1/zaken", {}),
    ("kiss-adapter", "GET", "/catalogi/api/v1/zaaktypen", {}),
    ("kiss-adapter", "GET", "/documenten/api/v1/enkelvoudiginformatieobjecten", {}),
    ("kiss-adapter", "GET", "/api/v2/objects", {}),
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
@pytest.mark.source(
    "external ICATT-Menselijk-Digitaal/podiumd-adapter test/PodiumdAdapter.Web.Test/AuthTests.cs",
    "The adapter's /healthz answers 200 and every route refuses a request without a token.",
)
@pytest.mark.parametrize(("component", "path"), [requiring(c, c, p, test_id=f"{c}{p}") for c, p in HEALTH])
@pytest.mark.scenario("""
    When the health endpoint of each deployed component is called
    Then it answers 200 OK
""")
def test_health_endpoint(http: requests.Session, urls: dict[str, str], component: str, path: str) -> None:
    """The component's own health endpoint reports healthy."""
    expect_status(http.get(urls[component] + path), HTTPStatus.OK)


# The podiumd chart sets up no subscription of Open Notificaties on kanaal autorisaties (podiumd-chart-44).
ON_WITHOUT_AC_SUBSCRIPTION = pytest.mark.xfail(
    strict=True,
    reason="[podiumd-chart-44] the podiumd chart (4.10.1) gives Open Notificaties no subscription on kanaal "
    "autorisaties, so its cached applicaties never refresh (view-config: Listens to AC notifications? Nee)",
)


@pytest.mark.source(
    "upstream open-zaak/open-zaak docs/installation/post_install.rst",
    "After installation, /view-config/ shows whether the site domain and the Notificaties API are configured.",
)
@pytest.mark.parametrize(
    "component",
    [requiring(c, c, marks=[ON_WITHOUT_AC_SUBSCRIPTION] if c == "opennotificaties" else []) for c in VIEW_CONFIG_APPS],
)
@pytest.mark.scenario("""
    Given each deployed app with a configuration page (Open Zaak, Open Notificaties)
    When the configuration page is opened
    Then every check of the site domain, the Notificaties API and the Autorisaties API passes
""")
def test_view_config_checks_pass(http: requests.Session, urls: dict[str, str], component: str) -> None:
    """The app's /view-config/ page marks no configuration check failed."""
    assert view_config_problems(http, urls[component]) == []


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
@pytest.mark.source(
    "external ICATT-Menselijk-Digitaal/podiumd-adapter test/PodiumdAdapter.Web.Test/AuthTests.cs",
    "The adapter's /healthz answers 200 and every route refuses a request without a token.",
)
@pytest.mark.parametrize(
    ("component", "method", "path", "headers"),
    [requiring(c, c, m, p, h, test_id=f"{c}{p}{'-wrong-key' if h else ''}") for c, m, p, h in ANONYMOUS],
)
@pytest.mark.scenario("""
    Given a request without credentials, or with a wrong API key
    When it calls each protected API endpoint
    Then the API answers 401 or 403
""")
def test_anonymous_call_is_refused(
    http: requests.Session, urls: dict[str, str], component: str, method: str, path: str, headers: dict[str, str]
) -> None:
    """Without (valid) credentials the API answers 401 or 403, not data and not a server error.

    POSTs carry a harmless body; they are refused before anything is stored.
    """
    body = None
    if method == "POST":
        body = {"FunctionalRoleNames": ["ptest"]} if component == "pabc" else {}
    response = http.request(method, urls[component] + path, json=body, headers=headers, allow_redirects=False)
    expect_status(response, *REFUSED)


@pytest.mark.requires("omc", "cluster")
@pytest.mark.source("TA smoke/79-omc-health.spec.ts", "NotifyNL OMC health and auth: OMC's Version endpoint answers.")
@pytest.mark.source(
    "EX tests/smoke/79-omc-health.spec.ts", "NotifyNL OMC health and auth: OMC's Version endpoint answers."
)
@pytest.mark.scenario("""
    Given a token signed with OMC's own JWT settings
    When the token is used to ask OMC for its version
    Then OMC answers 200 OK
""")
def test_omc_version_answers_to_its_token(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str]
) -> None:
    """OMC answers /Events/Version to a token from its own JWT settings and secret omc_jwt_secret."""
    token = omc_token(podiumd_env, time.time())
    expect_status(
        http.get(f"{urls['omc']}/Events/Version", headers={"Authorization": f"Bearer {token}"}), HTTPStatus.OK
    )


# OMC's /Test check of a service it calls, and OMC's setting with that service's URL.
OMC_SERVICES = [
    ("ZGW/OpenZaakHealthCheck", "ZGW_ENDPOINT_OPENZAAK"),
    ("ZGW/OpenKlantHealthCheck", "ZGW_ENDPOINT_OPENKLANT"),
    ("ZGW/OpenBesluitenHealthCheck", "ZGW_ENDPOINT_BESLUITEN"),
    ("ZGW/OpenObjectenHealthCheck", "ZGW_ENDPOINT_OBJECTEN"),
    ("ZGW/OpenObjectTypenHealthCheck", "ZGW_ENDPOINT_OBJECTTYPEN"),
    ("Notify/HealthCheck", "NOTIFY_API_BASEURL"),
]


@pytest.mark.requires("omc", "cluster")
@pytest.mark.source(
    "upstream Worth-NL/NotifyNL-OMC omc-notify.gitbook.io Test endpoints",
    "OMC's /Test endpoints tell whether OMC reaches each service it calls.",
)
@pytest.mark.parametrize(("check", "setting"), [pytest.param(c, s, id=c.split("/")[1]) for c, s in OMC_SERVICES])
@pytest.mark.scenario("""
    Given OMC has the URL of a service it calls
    When OMC's test endpoint for that service is called with OMC's own token
    Then OMC answers that it reaches the service
""")
def test_omc_reaches_its_services(
    http: requests.Session, podiumd_env: Environment, urls: dict[str, str], check: str, setting: str
) -> None:
    """OMC's GET /Test/<check> answers 202 for each service whose URL OMC has."""
    if not podiumd_env.variable("omc", setting):
        pytest.skip(f"OMC's {setting} is empty: OMC calls no such service")
    if setting == "NOTIFY_API_BASEURL" and notify_mock_missing(podiumd_env) is None:
        pytest.skip("OMC's Notify is podiumd-tests' mock server, which has no /_status")
    token = omc_token(podiumd_env, time.time())
    response = http.get(f"{urls['omc']}/Test/{check}", headers={"Authorization": f"Bearer {token}"})
    expect_status(response, HTTPStatus.ACCEPTED)
