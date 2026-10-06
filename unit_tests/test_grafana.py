"""Unit tests for the Grafana client."""

import pytest
import requests

from podiumd_tests.credentials import env_var_name
from podiumd_tests.grafana import Grafana
from podiumd_tests.grafana import GrafanaError
from podiumd_tests.grafana import down_targets
from podiumd_tests.grafana import grafana_auth
from podiumd_tests.grafana import target_count
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
            ]
        }
    }
    assert target_count(body) == 2
    assert down_targets(body) == ["tempo http://tempo:3200/metrics: connection refused"]
    assert down_targets({"data": {}}) == []
    assert target_count({}) == 0


def test_grafana_auth_needs_both_secrets(env_factory):
    assert grafana_auth(env_factory().credentials) is None
    only_user = {env_var_name("grafana_username"): "viewer"}
    assert grafana_auth(env_factory(environ=only_user).credentials) is None
    both = {**only_user, env_var_name("grafana_password"): "pw-1234"}
    assert grafana_auth(env_factory(environ=both).credentials) == ("viewer", "pw-1234")
