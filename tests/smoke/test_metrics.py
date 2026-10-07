"""Are metrics and logs flowing? Checked through Grafana's datasource proxy.

Ported from MK/PI test_metrics.py and test_monitoring_logging.py. Datasource
names differ per estate ("loki" vs "Loki"), so they are found by type; the Loki
test skips where no Loki datasource exists. Grafana outside minikube needs the
secrets grafana_username and grafana_password.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.grafana import Grafana
from podiumd_tests.grafana import down_targets
from podiumd_tests.grafana import grafana_auth
from podiumd_tests.grafana import target_count
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.requires("grafana")]


@pytest.fixture(scope="module", name="grafana")
def fixture_grafana(http: requests.Session, urls: dict[str, str], credentials: SecretResolver) -> Grafana:
    """Grafana with its datasources loaded; skip when Grafana needs a login the profile does not provide."""
    auth = grafana_auth(credentials)
    grafana = Grafana(http, urls["grafana"], auth)
    response = grafana.load_datasources()
    if response.status_code in REFUSED and auth is None:
        pytest.skip("Grafana needs a login: add secrets grafana_username and grafana_password to the profile")
    expect_status(response, HTTPStatus.OK)
    return grafana


def test_prometheus_datasource_provisioned(grafana: Grafana) -> None:
    """Grafana has a Prometheus datasource."""
    kinds = sorted({str(d.get("type")) for d in grafana.datasources})
    assert grafana.uid("prometheus"), f"no prometheus datasource; types: {kinds}"


def test_prometheus_scrape_targets_up(grafana: Grafana) -> None:
    """Prometheus has scrape targets, and all of them are up."""
    if not grafana.uid("prometheus"):
        pytest.skip("no prometheus datasource")
    body = grafana.proxy("prometheus", "/api/v1/targets")
    assert target_count(body), "no active scrape targets"
    down = down_targets(body)
    assert not down, f"scrape targets down: {down}"


def test_loki_has_pod_logs(grafana: Grafana, podiumd_env: Environment) -> None:
    """Loki has recent log streams of the application namespace (Alloy forwards them)."""
    if not grafana.uid("loki"):
        pytest.skip("no loki datasource (metrics without logging)")
    query = f'{{namespace="{podiumd_env.profile.kube.namespace}"}}'
    body = grafana.proxy("loki", "/loki/api/v1/query_range", {"query": query, "limit": "5"})
    assert body["status"] == "success"
    assert cast("dict[str, object]", body["data"])["result"], f"no log streams for {query}: is Alloy forwarding logs?"
