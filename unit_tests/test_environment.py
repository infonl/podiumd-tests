"""Unit tests for the environment: console URLs and admin hosts."""

import json

from contextlib import contextmanager

from podiumd_tests.kube import Kube


def test_console_urls_forward_only_present_in_cluster_urls(profile_factory, fake_runner, env_factory, monkeypatch):
    forwards = []

    @contextmanager
    def port_forward(_kube, service, port, *, namespace=None):
        forwards.append((service, port, namespace))
        yield 41235

    monkeypatch.setattr(Kube, "port_forward", port_forward)
    deployments = {"items": [{"metadata": {"name": "frankgateway-outway"}}]}
    fake_runner.answers["get deployments"] = (0, json.dumps(deployments))
    urls = {
        "frankgateway": "http://frankgateway-outway.podiumd.svc.cluster.local:9080/base",
        "openzaak": "https://openzaak.example.test",
    }
    with env_factory(profile_factory(urls=urls)).console_urls() as console:
        assert console == {"frankgateway": "http://127.0.0.1:41235/base", "openzaak": urls["openzaak"]}
    assert forwards == [("frankgateway-outway", 9080, "podiumd")]


def test_admin_of_is_the_app_whose_deployment_serves_it(profile_factory, fake_runner, env_factory):
    urls = {"objecten": "https://objecten.example.test", "objecttypen": "https://objecttypen.example.test"}
    env = env_factory(profile_factory(urls=urls))
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [{"metadata": {"name": "objecten"}}]}))
    assert env.admin_of("objecttypen") == "objecten"


def test_admin_of_is_itself_with_its_own_deployment(profile_factory, fake_runner, env_factory):
    urls = {"objecten": "https://objecten.example.test", "objecttypen": "https://objecttypen.example.test"}
    env = env_factory(profile_factory(urls=urls))
    names = [{"metadata": {"name": n}} for n in ("objecten", "objecttypen")]
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": names}))
    assert env.admin_of("objecttypen") == "objecttypen"
