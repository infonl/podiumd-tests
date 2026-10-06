"""Are metrics and logs flowing? Through Grafana's datasource proxy.

Merges MK/PI test_metrics.py and test_monitoring_logging.py. Those two differ
in which datasources exist (Prometheus+Tempo vs Prometheus+Loki+Tempo) and in
their names ("loki" vs "Loki"); here datasources are found by type, and the
Loki check runs only where a Loki datasource exists.
Grafana answers anonymously on minikube; elsewhere set the secrets
grafana_username and grafana_password in the profile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

import pytest

if TYPE_CHECKING:
    import requests

    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.requires("grafana")]

type Json = dict[str, object]


@pytest.fixture(scope="module", name="grafana")
def fixture_grafana(http: requests.Session, urls: dict[str, str], podiumd_env: Environment) -> GrafanaApi:
    """Grafana API client; skip when Grafana needs a login the profile does not provide."""
    secrets = podiumd_env.profile.secrets
    auth = None
    if "grafana_username" in secrets and "grafana_password" in secrets:
        credentials = podiumd_env.credentials
        auth = (credentials.get("grafana_username"), credentials.get("grafana_password"))
    api = GrafanaApi(http, urls["grafana"], auth)
    response = api.get("/api/datasources")
    if response.status_code in {401, 403} and auth is None:
        pytest.skip("Grafana needs a login: add secrets grafana_username and grafana_password to the profile")
    assert response.status_code == 200, f"/api/datasources: HTTP {response.status_code}"
    api.datasources = cast("list[Json]", response.json())
    return api


class GrafanaApi:
    """Calls to Grafana and through its datasource proxy."""

    def __init__(self, http: requests.Session, base: str, auth: tuple[str, str] | None) -> None:
        self.http = http
        self.base = base
        self.auth = auth
        self.datasources: list[Json] = []

    def get(self, path: str, params: dict[str, str] | None = None) -> requests.Response:
        """GET a Grafana path."""
        return self.http.get(self.base + path, params=params, auth=self.auth)

    def uid(self, kind: str) -> str | None:
        """uid of the first datasource of a type (prometheus, loki, tempo), or None."""
        return next((str(d["uid"]) for d in self.datasources if d.get("type") == kind), None)

    def proxy(self, kind: str, path: str, params: dict[str, str] | None = None) -> Json:
        """GET through the datasource proxy; the JSON body."""
        response = self.get(f"/api/datasources/proxy/uid/{self.uid(kind)}{path}", params)
        assert response.status_code == 200, f"{kind}{path}: HTTP {response.status_code}"
        return cast("Json", response.json())


def test_prometheus_datasource_provisioned(grafana: GrafanaApi) -> None:
    """Grafana has a Prometheus datasource."""
    kinds = sorted({str(d.get("type")) for d in grafana.datasources})
    assert grafana.uid("prometheus"), f"no prometheus datasource; types: {kinds}"


def test_prometheus_scrape_targets_up(grafana: GrafanaApi) -> None:
    """Prometheus has scrape targets, and all of them are up."""
    if not grafana.uid("prometheus"):
        pytest.skip("no prometheus datasource")
    data = cast("Json", grafana.proxy("prometheus", "/api/v1/targets")["data"])
    targets = cast("list[Json]", data["activeTargets"])
    assert targets, "no active scrape targets"
    down = [
        f"{cast('Json', t['labels']).get('job')} {t.get('scrapeUrl')}: {t.get('lastError')}"
        for t in targets
        if t.get("health") != "up"
    ]
    assert not down, f"scrape targets down: {down}"


def test_loki_has_pod_logs(grafana: GrafanaApi, podiumd_env: Environment) -> None:
    """Loki has recent log streams of the application namespace (Alloy forwards them)."""
    if not grafana.uid("loki"):
        pytest.skip("no loki datasource (metrics without logging)")
    query = f'{{namespace="{podiumd_env.profile.kube.namespace}"}}'
    body = grafana.proxy("loki", "/loki/api/v1/query_range", {"query": query, "limit": "5"})
    assert body["status"] == "success"
    assert cast("Json", body["data"])["result"], f"no log streams for {query}: is Alloy forwarding logs?"
