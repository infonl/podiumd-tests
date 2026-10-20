"""Are metrics and logs flowing? Checked through Grafana's datasource proxy.

Ported from MK/PI test_metrics.py and test_monitoring_logging.py. Datasource
names differ per estate ("loki" vs "Loki"), so they are found by type; the Loki
tests skip where no Loki datasource exists. Grafana outside minikube needs the
secrets grafana_username and grafana_password.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.grafana import MONITOR_POOLS
from podiumd_tests.grafana import Grafana
from podiumd_tests.grafana import down_targets
from podiumd_tests.grafana import grafana_auth
from podiumd_tests.grafana import monitors_without_targets
from podiumd_tests.grafana import pods_in_loki
from podiumd_tests.grafana import running_pods_not_in_loki
from podiumd_tests.grafana import target_count
from podiumd_tests.json_data import section
from podiumd_tests.kube import metadata_name
from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import expect_status

if TYPE_CHECKING:
    import requests

    from podiumd_tests.credentials import SecretResolver
    from podiumd_tests.environment import Environment

pytestmark = [pytest.mark.smoke, pytest.mark.requires("grafana")]

# Known monitors without targets, by name suffix: they xfail instead of fail.
EMPTY_MONITORS = {
    "-traefik": "[podiumd-chart-14] monitoring-logging 1.0.18 renders a Traefik PodMonitor by default, but the edge"
    " is NGINX Gateway Fabric; fixed in monitoring-logging 1.0.19 (helm-charts #622)",
    **dict.fromkeys(
        ("-kube-controller-manager", "-kube-etcd", "-kube-scheduler", "-kube-proxy"),
        "[podiumd-chart-18] kube-prometheus-stack's control-plane and kube-proxy monitors have no targets on AKS"
        " (managed control plane; Cilium without kube-proxy); off by default in monitoring-logging 1.0.19"
        " (helm-charts #481)",
    ),
}


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


@pytest.mark.cluster
@pytest.mark.requires("cluster")
def test_every_monitor_has_scrape_targets(grafana: Grafana, podiumd_env: Environment) -> None:
    """Every ServiceMonitor and PodMonitor has scrape targets: Prometheus selects it and it matches running pods."""
    if not grafana.uid("prometheus"):
        pytest.skip("no prometheus datasource")
    monitors = [
        f"{pool}/{section(m, 'metadata').get('namespace')}/{metadata_name(m)}"
        for kind, pool in MONITOR_POOLS.items()
        for m in podiumd_env.items(kind)
    ]
    if not monitors:
        pytest.skip("no ServiceMonitor or PodMonitor in the environment's namespaces")
    missing = monitors_without_targets(monitors, grafana.proxy("prometheus", "/api/v1/targets"))
    known = {reason for m in missing for suffix, reason in EMPTY_MONITORS.items() if m.endswith(suffix)}
    unknown = [m for m in missing if not any(m.endswith(suffix) for suffix in EMPTY_MONITORS)]
    assert not unknown, f"monitors without scrape targets: {unknown}"
    if known:
        pytest.xfail("; ".join(sorted(known)))


@pytest.mark.cluster
@pytest.mark.requires("cluster")
def test_every_pod_logs_to_loki(grafana: Grafana, podiumd_env: Environment) -> None:
    """Every running pod that wrote log lines in the last 24 h has log lines in Loki."""
    if not grafana.uid("loki"):
        pytest.skip("no loki datasource (metrics without logging)")
    query = f'sum by (namespace, pod) (count_over_time({{namespace=~"{"|".join(podiumd_env.namespaces)}"}}[24h]))'
    in_loki = pods_in_loki(grafana.proxy("loki", "/loki/api/v1/query", {"query": query}))
    candidates = running_pods_not_in_loki(podiumd_env.items("pods"), in_loki, datetime.now(UTC))
    missing = [
        f"{section(p, 'metadata').get('namespace')}/{metadata_name(p)}"
        for p in candidates
        if podiumd_env.kube.run(
            "logs",
            f"pod/{metadata_name(p)}",
            "--all-containers",
            "--since=24h",
            "--tail=1",
            namespace=str(section(p, "metadata").get("namespace")),
        ).strip()
    ]
    assert not missing, f"pods whose logs are not in Loki: {missing}"
