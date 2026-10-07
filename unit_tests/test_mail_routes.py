"""Unit tests for reading where apps send mail."""

import base64
import json

from podiumd_tests.mail_routes import MailRoute
from podiumd_tests.mail_routes import cluster_hosts
from podiumd_tests.mail_routes import is_internal
from podiumd_tests.mail_routes import mail_stays_internal
from podiumd_tests.mail_routes import workload_routes


def test_rule_applies_to_minikube_and_qa_only(profile_factory):
    assert mail_stays_internal(profile_factory(estate="minikube"))
    assert mail_stays_internal(profile_factory(estate="podiumd-infra"))
    assert not mail_stays_internal(profile_factory(estate="externals"))


def test_internal_hosts_are_cluster_services_or_no_server(env_factory, fake_runner):
    services = [
        {"metadata": {"name": "mailpit", "namespace": "podiumd"}, "spec": {"clusterIP": "10.96.0.9"}},
        {"metadata": {"name": "smtp-relay", "namespace": "mail"}, "spec": {"clusterIP": "10.96.0.10"}},
    ]
    fake_runner.answers["get services"] = (0, json.dumps({"items": services}))
    internal = cluster_hosts(env_factory())
    inside = ("mailpit", "mailpit.podiumd.svc.cluster.local", "smtp-relay.mail", "10.96.0.10", "", "localhost")
    assert all(is_internal(h, internal) for h in inside)
    assert not any(is_internal(h, internal) for h in ("smtp.office365.com", "mailpit.example.com", "10.1.2.3"))


def test_routes_come_from_literals_configmaps_and_secrets(env_factory, fake_runner):
    container = {
        "name": "web",
        "env": [
            {"name": "EMAIL_HOST", "value": "mailpit"},
            {"name": "SMTP_SERVER", "valueFrom": {"secretKeyRef": {"name": "mail", "key": "SMTP_SERVER"}}},
            {"name": "OTHER", "value": "x"},
        ],
        "envFrom": [{"configMapRef": {"name": "app-env"}}],
    }
    deployment = {
        "metadata": {"name": "app", "namespace": "podiumd"},
        "spec": {"template": {"spec": {"containers": [container]}}},
    }
    secret = {"data": {"SMTP_SERVER": base64.b64encode(b"smtp.example.com").decode(), "PASSWORD": "c2VjcmV0"}}
    fake_runner.answers["get deployments"] = (0, json.dumps({"items": [deployment]}))
    fake_runner.answers["get statefulsets"] = (0, json.dumps({"items": []}))
    fake_runner.answers["get configmap app-env"] = (0, json.dumps({"data": {"MAIL_HOST": "relay", "DEBUG": "1"}}))
    fake_runner.answers["get secret mail"] = (0, json.dumps(secret))
    assert sorted(workload_routes(env_factory()), key=lambda r: r.where) == [
        MailRoute("app/web EMAIL_HOST", "mailpit"),
        MailRoute("app/web MAIL_HOST", "relay"),
        MailRoute("app/web SMTP_SERVER", "smtp.example.com"),
    ]
