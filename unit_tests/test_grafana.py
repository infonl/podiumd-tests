"""Unit tests for the Grafana client."""

from datetime import UTC
from datetime import datetime
from datetime import timedelta

import pytest
import requests

from podiumd_tests.credentials import env_var_name
from podiumd_tests.grafana import Grafana
from podiumd_tests.grafana import GrafanaError
from podiumd_tests.grafana import down_targets
from podiumd_tests.grafana import grafana_auth
from podiumd_tests.grafana import monitors_without_targets
from podiumd_tests.grafana import otel_jobs_query
from podiumd_tests.grafana import pods_in_loki
from podiumd_tests.grafana import running_pods_not_in_loki
from podiumd_tests.grafana import target_count
from podiumd_tests.grafana import without_metrics
from podiumd_tests.responses import UnexpectedStatusError

DATASOURCES = [
    {"name": "Prometheus", "type": "prometheus", "uid": "prom-1"},
    {"name": "loki", "type": "loki", "uid": "loki-1"},
]


BASE = "https://grafana.example.test"


def grafana_with(_sent, auth=None):
    """A Grafana with datasources loaded; _sent only makes callers install the fake answers first."""
    grafana = Grafana(requests.Session(), BASE, auth)
    grafana.load_datasources()
    return grafana


def test_datasources_are_found_by_type(fake_http):
    grafana = grafana_with(fake_http({"/api/datasources": (200, DATASOURCES)}))
    assert grafana.uid("loki") == "loki-1"
    assert grafana.uid("tempo") is None


def test_login_problem_leaves_no_datasources(fake_http):
    fake_http({"/api/datasources": (401, {"message": "Unauthorized"})})
    grafana = Grafana(requests.Session(), BASE)
    assert grafana.load_datasources().status_code == 401
    assert grafana.datasources == []


def test_proxy_goes_through_the_datasource_uid_with_auth(fake_http):
    sent = fake_http(
        {
            "/api/datasources": (200, DATASOURCES),
            "/api/datasources/proxy/uid/loki-1/loki/api/v1/query_range": (200, {"status": "success"}),
        }
    )
    grafana = grafana_with(sent, auth=("viewer", "pw"))
    assert grafana.proxy("loki", "/loki/api/v1/query_range", {"limit": "5"}) == {"status": "success"}
    assert sent[-1].url == f"{BASE}/api/datasources/proxy/uid/loki-1/loki/api/v1/query_range?limit=5"
    assert sent[-1].headers["Authorization"].startswith("Basic ")


def test_proxy_errors(fake_http):
    grafana = grafana_with(fake_http({"/api/datasources": (200, DATASOURCES)}))
    with pytest.raises(GrafanaError, match="no tempo datasource"):
        grafana.proxy("tempo", "/api/search")
    with pytest.raises(UnexpectedStatusError, match="HTTP 404, expected 200"):
        grafana.proxy("prometheus", "/api/v1/targets")


def test_down_targets():
    body = {
        "data": {
            "activeTargets": [
                {"labels": {"job": "zac-admin"}, "scrapeUrl": "http://zac:9990/metrics", "health": "up"},
                {
                    "labels": {"job": "tempo"},
                    "scrapeUrl": "http://tempo:3200/metrics",
                    "health": "down",
                    "lastError": "connection refused",
                },
                {
                    "labels": {"job": "elastic-operator"},
                    "scrapeUrl": "http://eck:8080/metrics",
                    "health": "unknown",
                    "lastError": "",
                    "scrapeInterval": "5m",
                    "scrapeTimeout": "10s",
                },
            ]
        }
    }
    assert target_count(body) == 3
    assert down_targets(body, timedelta(minutes=5)) == ["tempo http://tempo:3200/metrics: connection refused"]
    assert down_targets(body, timedelta(minutes=6))[1] == "elastic-operator http://eck:8080/metrics: unknown"
    assert down_targets({"data": {}}, timedelta()) == []
    assert target_count({}) == 0


def test_grafana_auth_needs_both_secrets(env_factory):
    assert grafana_auth(env_factory().credentials) is None
    only_user = {env_var_name("grafana_username"): "viewer"}
    assert grafana_auth(env_factory(environ=only_user).credentials) is None
    both = {**only_user, env_var_name("grafana_password"): "pw-1234"}
    assert grafana_auth(env_factory(environ=both).credentials) == ("viewer", "pw-1234")


def test_monitor_without_active_target_is_reported():
    body = {"data": {"activeTargets": [{"scrapePool": "serviceMonitor/ns/keycloak/0", "health": "up"}]}}
    monitors = ["serviceMonitor/ns/keycloak", "podMonitor/ns/traefik", "serviceMonitor/ns/keycloak-operator"]
    assert monitors_without_targets(monitors, body) == ["podMonitor/ns/traefik", "serviceMonitor/ns/keycloak-operator"]


def test_otel_jobs_query_uses_the_otel_service_names():
    query = otel_jobs_query(["openformulieren", "keycloak", "objecten"])
    assert query == 'group by (job) ({job=~"(.+/)?(openforms|openobject)(-.+)?"})'


def test_without_metrics():
    targets = {
        "data": {
            "activeTargets": [
                {"scrapePool": "serviceMonitor/ns/keycloak/0", "health": "up"},
                {"scrapePool": "podMonitor/ns/redis-ha/0", "health": "down"},
                {"scrapePool": "serviceMonitor/ns/frankgateway-outway/0", "health": "up"},
                {"scrapePool": "kubernetes-pods", "health": "up"},
            ]
        }
    }
    otel = {
        "data": {
            "result": [
                {"metric": {"job": "openzaak"}},
                {"metric": {"job": "podiumd/openforms"}},
                {"metric": {"job": "openinwoner-web"}},
                {"metric": {"job": "openobjectx"}},
                {"metric": {"job": "podiumd/zac"}},
            ]
        }
    }
    components = ["keycloak", "redis", "frankgateway", "clamav", "openzaak", "openformulieren", "openvtb", "zac"]
    components += ["openinwoner", "objecten"]
    assert without_metrics(components, targets, otel) == (["clamav", "redis"], ["objecten", "openvtb"])


def pod(name, phase="Running", created="2026-10-20T08:00:00Z"):
    return {"metadata": {"namespace": "ns", "name": name, "creationTimestamp": created}, "status": {"phase": phase}}


def test_running_pods_not_in_loki_skips_young_and_finished_pods():
    body = {"data": {"result": [{"metric": {"namespace": "ns", "pod": "logged"}, "value": [0, "3"]}]}}
    pods = [pod("logged"), pod("silent"), pod("young", created="2026-10-20T08:55:00Z"), pod("done", phase="Succeeded")]
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    assert running_pods_not_in_loki(pods, pods_in_loki(body), now) == [pods[1]]
