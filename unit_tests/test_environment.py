"""Unit tests for the environment's console URLs."""

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
