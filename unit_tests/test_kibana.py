"""Unit tests for KISS's Kibana status."""

import json

import pytest

from podiumd_tests.kibana import kibana_status_level
from podiumd_tests.kube import Kube

STATUS = json.dumps({"status": {"overall": {"level": "available"}}})


@pytest.mark.parametrize(("port", "scheme"), [("https", "https"), ("http", "http")])
def test_status_level_over_the_scheme_of_the_service(fake_runner, port, scheme):
    fake_runner.answers["get service kiss-kb-http"] = (0, json.dumps({"spec": {"ports": [{"name": port}]}}))
    fake_runner.answers["exec -i deploy/kiss-kb"] = (0, STATUS)
    assert kibana_status_level(Kube("ctx", "podiumd", fake_runner), "s3cret") == "available"
    assert fake_runner.calls[-1][-1] == f"{scheme}://localhost:5601/api/status"
    assert fake_runner.stdins[-1] == 'user = "elastic:s3cret"\n'
    assert "s3cret" not in " ".join(fake_runner.calls[-1])


def test_no_service_is_no_kibana(fake_runner):
    fake_runner.answers["get service kiss-kb-http"] = (0, "")
    assert kibana_status_level(Kube("ctx", "podiumd", fake_runner), "s3cret") is None
