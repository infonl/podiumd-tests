"""Unit tests for exporting and validating estate profiles."""

import json

from datetime import UTC
from datetime import datetime

import pytest
import yaml

from podiumd_tests import estate_profile
from podiumd_tests.config import ProfileError
from podiumd_tests.kube import KubeError

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
OPERATOR_LOG = (
    'WARN [org.keycloak.events] type="CLIENT_LOGIN_ERROR", realmName="master", clientId="keycloak-operator",'
    ' error="client_not_found"'
)
OTP_LOG = (
    "ERROR Uncaught server error: org.keycloak.authentication.AuthenticationFlowException: direct-grant-validate-otp"
)
KEYCLOAK = {
    "metadata": {
        "name": "keycloak",
        "namespace": "podiumd",
        "labels": {"app.kubernetes.io/managed-by": "keycloak-operator"},
    },
    "spec": {
        "replicas": 2,
        "selector": {"matchLabels": {"app": "keycloak"}},
        "template": {"spec": {"containers": [{"image": "quay.io/keycloak/keycloak:26.0.7"}]}},
    },
}
OPERATOR = {
    "metadata": {
        "name": "keycloak-operator",
        "labels": {
            "app.kubernetes.io/name": "keycloak-operator",
            "app.kubernetes.io/version": "26.0.7",
            "helm.sh/chart": "keycloak-operator-1.13.1",
        },
    },
}
PODIUMD_CONFIG = {"metadata": {"labels": {"app.kubernetes.io/name": "podiumd", "app.kubernetes.io/version": "4.11.0"}}}
HUNG = {
    "metadata": {"name": "ensure-keycloak-operator-sa"},
    "status": {"startTime": "2026-11-24T10:00:00Z", "active": 1},
}
FAILED = {
    "metadata": {"name": "podiumd-realm", "ownerReferences": [{"kind": "KeycloakRealmImport"}]},
    "status": {"conditions": [{"type": "Failed", "status": "True"}]},
}
OTHER = {"metadata": {"name": "openzaak-migrate"}, "status": {"conditions": [{"type": "Failed", "status": "True"}]}}


def items(*found):
    return (0, json.dumps({"items": list(found)}))


def cluster(fake_runner, log="", statefulsets=(KEYCLOAK,)):
    fake_runner.answers = {
        "get --raw /readyz": (0, "ok"),
        "version -o json": (0, json.dumps({"serverVersion": {"gitVersion": "v1.32.3"}})),
        "get statefulsets": items(*statefulsets),
        "get deployments": items(OPERATOR),
        "get configmaps": items(PODIUMD_CONFIG),
        "get nodes": items(
            {"metadata": {"labels": {"kubernetes.azure.com/agentpool": "apps"}}},
            {"metadata": {"labels": {"agentpool": "system"}}},
        ),
        "k8s-app=cilium": items({"metadata": {"name": "cilium-1"}}),
        "get services": items(),
        "logs -l app=keycloak": (0, log),
        "get jobs": items(HUNG, FAILED, OTHER),
        "get keycloaks": (1, "Error from server (Forbidden): keycloaks is forbidden"),
    }


def exported(env):
    """The environment's profile as its YAML file holds it."""
    return yaml.safe_load(estate_profile.dump(estate_profile.export(env, "24h", NOW)))


def test_export_reads_the_cluster_and_derives_keycloak_master_from_the_log(env_factory, fake_runner):
    cluster(fake_runner, log=f"{OPERATOR_LOG}\n{OPERATOR_LOG}\n{OTP_LOG}\n")
    profile = exported(env_factory())
    assert estate_profile.validate(profile, "p") == profile
    assert profile["source"] == "kubectl"
    assert profile["chart"] == {"podiumd": "4.11.0", "components": {"keycloak-operator": "1.13.1"}}
    assert profile["cluster"] == {
        "kubernetes": "v1.32.3",
        "nodes": 2,
        "node_pools": ["apps", "system"],
        "cni": "cilium",
    }
    assert profile["keycloak"] == {"replicas": 2, "version": "26.0.7"}
    master = profile["keycloak_master"]
    assert (master["operator_client"], master["direct_grant_otp"], master["otp_policy"]) == (
        "absent",
        "required",
        "unknown",
    )
    assert master["reasons"]["operator_client"].startswith(
        "Keycloak log of 24h: 2 client_not_found logins of keycloak-operator"
    )
    signals = profile["signals"]
    assert (signals["operator_client_not_found"], signals["otp_flow_errors"]) == (2, 1)
    assert signals["keycloak_jobs_failed"] == ["podiumd-realm"]
    assert signals["keycloak_jobs_hanging"] == ["ensure-keycloak-operator-sa"]
    assert any("--since=86400s" in call for call in fake_runner.calls)


def forbid(fake_runner, *fragments):
    refused = {
        fragment: (1, f"Error from server (Forbidden): {fragment} at https://api.x.example.net:443")
        for fragment in fragments
    }
    kept = {fragment: answer for fragment, answer in fake_runner.answers.items() if fragment not in refused}
    fake_runner.answers = {**refused, **kept}


def test_export_marks_what_read_only_access_cannot_read_unknown(env_factory, fake_runner):
    cluster(fake_runner, statefulsets=())
    forbid(fake_runner, "get nodes", "get jobs", "version -o json", "k8s-app=cilium")
    profile = exported(env_factory())
    assert profile["cluster"]["reasons"] == {
        "kubernetes": "Error from server (Forbidden): version -o json at <host>",
        "nodes": "Error from server (Forbidden): get nodes at <host>",
        "node_pools": "Error from server (Forbidden): get nodes at <host>",
        "cni": "cannot read namespace kube-system: Error from server (Forbidden): k8s-app=cilium at <host>",
    }
    assert profile["keycloak"]["reasons"]["version"] == "no Keycloak StatefulSet"
    assert profile["signals"]["keycloak_jobs_failed"] == "unknown"
    assert profile["keycloak_master"]["reasons"]["operator_client"] == "no Keycloak admin credentials in the profile"


def test_forbidden_pod_logs_make_the_log_signals_unknown(env_factory, fake_runner):
    cluster(fake_runner)
    forbid(fake_runner, "logs -l")
    signals = exported(env_factory())["signals"]
    assert signals["otp_flow_errors"] == "unknown"
    assert signals["reasons"]["operator_client_not_found"] == "Error from server (Forbidden): logs -l at <host>"


def test_a_digest_pinned_keycloak_takes_the_operators_version(env_factory, fake_runner):
    template = {"spec": {"containers": [{"image": "quay.io/keycloak/keycloak@sha256:ab"}]}}
    pinned = {**KEYCLOAK, "spec": {**KEYCLOAK["spec"], "template": template}}
    cluster(fake_runner, statefulsets=(pinned,))
    keycloak = exported(env_factory())["keycloak"]
    assert keycloak["version"] == "26.0.7"
    assert "keycloak-operator" in keycloak["reasons"]["version"]


ADMIN_ENV = {
    "PODIUMD_TESTS_SECRET_KEYCLOAK_ADMIN_USERNAME": "admin",
    "PODIUMD_TESTS_SECRET_KEYCLOAK_ADMIN_PASSWORD": "pw",
}
MASTER = "/admin/realms/master"
EXECUTIONS = [
    {"id": "s", "level": 0, "displayName": "Conditional OTP", "requirement": "CONDITIONAL"},
    {"id": "c", "level": 1, "providerId": "conditional-user-configured", "requirement": "REQUIRED"},
    {"id": "o", "level": 1, "providerId": "direct-grant-validate-otp", "requirement": "REQUIRED"},
]


def test_export_reads_keycloak_master_with_admin_credentials(env_factory, fake_runner, fake_http):
    cluster(fake_runner, log=OPERATOR_LOG)
    fake_http(
        {
            "POST /realms/master/protocol/openid-connect/token": (200, {"access_token": "t"}),
            MASTER: (200, {"directGrantFlow": "direct grant", "otpPolicyType": "totp", "otpPolicyDigits": 6}),
            f"{MASTER}/authentication/flows/direct%20grant/executions": (200, EXECUTIONS),
            f"{MASTER}/clients": (200, [{"id": "k", "clientId": "keycloak-operator"}]),
            f"{MASTER}/roles/admin/users": (200, [{"requiredActions": ["CONFIGURE_TOTP"]}, {"requiredActions": []}]),
        }
    )
    profile = exported(env_factory(environ=ADMIN_ENV))
    assert profile["source"] == "keycloak-admin"
    assert profile["keycloak_master"] == {
        "direct_grant_otp": "conditional",
        "operator_client": "present",
        "required_actions": {"CONFIGURE_TOTP": 1},
        "otp_policy": {"type": "totp", "algorithm": None, "digits": 6, "period": None},
    }


def test_export_skips_the_admin_login_where_the_log_shows_master_requires_otp(env_factory, fake_runner, fake_http):
    cluster(fake_runner, log=OTP_LOG)
    sent = fake_http({})
    master = exported(env_factory(environ=ADMIN_ENV))["keycloak_master"]
    assert master["direct_grant_otp"] == "required"
    assert master["operator_client"] == "unknown"
    assert "so no admin login" in master["reasons"]["operator_client"]
    assert sent == []


def test_a_failed_admin_login_makes_keycloak_master_unknown(env_factory, fake_runner, fake_http):
    cluster(fake_runner)
    fake_http({"POST /realms/master/protocol/openid-connect/token": (401, {"error": "invalid_grant"})})
    master = exported(env_factory(environ=ADMIN_ENV))["keycloak_master"]
    assert master["reasons"]["direct_grant_otp"].startswith("Keycloak admin login failed: ")
    assert "kc-admin.example.test" not in master["reasons"]["direct_grant_otp"]


def test_an_unreachable_cluster_stops_the_export(env_factory, fake_runner):
    with pytest.raises(KubeError):
        exported(env_factory())
    assert fake_runner.calls


FORMS = {"metadata": {"name": "openformulieren"}}
SETUP = (
    "zgw_consumers_config_enable: true\nzgw_consumers:\n  services:\n  - identifier: openklant-api\n    api_type: kc\n"
)
FORMS_CONFIG = {"metadata": {"name": "openformulieren-configuration"}, "data": {"configuration.yaml": SETUP}}
ARGS = ["shell", "-c", 'from zgw_consumers.models import Service\nservice_identifier = "klant"\n']
LINK_JOB = {
    "metadata": {"name": "openformulieren-configure-customer-interactions-4f5b668e3f"},
    "spec": {"template": {"spec": {"containers": [{"args": ARGS}]}}},
    "status": {"conditions": [{"type": "Failed", "status": "True"}]},
}


def with_forms(fake_runner, *, jobs=(), configmaps=(FORMS_CONFIG,)):
    cluster(fake_runner)
    fake_runner.answers |= {
        "get deployments": items(OPERATOR, FORMS),
        "get configmaps": items(PODIUMD_CONFIG, *configmaps),
        "get jobs": items(*jobs),
    }


def test_export_reads_the_service_the_customer_interactions_job_expects(env_factory, fake_runner):
    with_forms(fake_runner, jobs=(LINK_JOB, OTHER))
    assert exported(env_factory())["openformulieren"] == {
        "deployed": True,
        "customer_interactions_jobs_failed": ["openformulieren-configure-customer-interactions-4f5b668e3f"],
        "customer_interactions_service": "klant",
        "service_defined": "absent",
    }


def test_without_the_job_export_checks_the_chart_default_service(env_factory, fake_runner):
    with_forms(fake_runner)
    forms = exported(env_factory())["openformulieren"]
    assert (forms["customer_interactions_service"], forms["service_defined"]) == ("openklant-api", "present")
    assert forms["reasons"] == {
        "customer_interactions_service": "no openformulieren-configure-customer-interactions Job: the chart default"
    }


def test_without_its_setup_configuration_the_service_is_unknown(env_factory, fake_runner):
    with_forms(fake_runner, configmaps=())
    forms = exported(env_factory())["openformulieren"]
    assert forms["service_defined"] == "unknown"
    assert forms["reasons"]["service_defined"].startswith("no ConfigMap openformulieren-configuration")


def test_without_open_formulieren_its_fields_are_unknown(env_factory, fake_runner):
    cluster(fake_runner)
    forms = exported(env_factory())["openformulieren"]
    assert (forms["deployed"], forms["service_defined"]) == (False, "unknown")
    assert forms["reasons"]["service_defined"] == "Open Formulieren is not deployed"


@pytest.mark.parametrize(
    ("configuration", "defined"),
    [
        (SETUP, "present"),
        (SETUP.replace("true", "false"), "absent"),
        (SETUP.replace("openklant-api", "openklant"), "absent"),
        ("", "absent"),
    ],
)
def test_service_defined_needs_zgw_consumers_enabled_and_the_identifier(configuration, defined):
    assert estate_profile.service_defined(configuration, "openklant-api") == defined


def test_service_defined_refuses_invalid_yaml():
    with pytest.raises(LookupError, match="no valid YAML"):
        estate_profile.service_defined("services: [", "openklant-api")


def test_reason_of_a_secret_error_is_the_kubectl_error_without_the_command():
    error = LookupError("secret 'x' (k8s_secret): kubectl --context ctx get secret s: Error from server (NotFound)")
    error.__cause__ = KubeError(["kubectl", "--context", "ctx", "get", "secret", "s"], "Error from server (NotFound)")
    assert estate_profile.reason(error) == "Error from server (NotFound)"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ([], "expected a mapping"),
        ({"source": "kubectl"}, "missing estate"),
        ({"estate": "e", "source": "guess"}, "source: .guess., expected one of"),
        ({"estate": "e", "source": "manual", "keycloak_master": []}, "keycloak_master: expected a mapping"),
        (
            {"estate": "e", "source": "manual", "keycloak_master": {"operator_client": "gone"}},
            "operator_client: 'gone'",
        ),
        (
            {"estate": "e", "source": "manual", "openformulieren": {"service_defined": "maybe"}},
            "service_defined: 'maybe'",
        ),
    ],
)
def test_validate_refuses_an_invalid_profile(raw, message):
    with pytest.raises(ProfileError, match=message):
        estate_profile.validate(raw, "p")


def test_load_reads_a_manual_profile_and_refuses_a_missing_file(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("estate: e\nsource: manual\nkeycloak_master: {direct_grant_otp: required}\n", encoding="utf-8")
    profile = estate_profile.load(path)
    assert estate_profile.master_value(profile, "direct_grant_otp") == "required"
    assert estate_profile.master_value(profile, "operator_client") == "unknown"
    with pytest.raises(ProfileError, match=r"absent\.yaml"):
        estate_profile.load(tmp_path / "absent.yaml")


def test_scrub_removes_the_readers_identity_from_an_rbac_refusal():
    refusal = 'nodes is forbidden: User "e34dc683-0000" cannot list resource "nodes" at the cluster scope'
    assert (
        estate_profile.scrub(refusal)
        == 'nodes is forbidden: User <reader> cannot list resource "nodes" at the cluster scope'
    )
