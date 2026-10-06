"""Unit tests for capability detection and component aliases."""

from podiumd_tests.capabilities import detect
from podiumd_tests.components import component_for_host_label
from podiumd_tests.components import deployed_components


def test_profile_alone_decides_without_cluster(profile_factory):
    caps = detect(profile_factory(), None)
    assert caps.present == {"openzaak", "keycloak-admin"}
    assert caps.skip_reason("openzaak") is None
    assert caps.skip_reason("zac") == "requires: zac (no URL in profile)"


def test_configured_but_not_deployed_is_absent(profile_factory):
    caps = detect(profile_factory(), ["keycloak-0"])
    # keycloak-admin has no deployment of its own, so its URL is enough.
    assert caps.present == {"keycloak-admin"}
    assert caps.skip_reason("openzaak") == "requires: openzaak (no deployment in namespace podiumd)"


def test_deployment_aliases():
    names = ["notificaties-celery", "openzaak", "podiumd-grafana", "kiss-frontend"]
    assert deployed_components(names) == {"opennotificaties", "openzaak", "grafana", "kiss"}


def test_host_aliases():
    assert component_for_host_label("contact") == "kiss"
    assert component_for_host_label("mijn") == "openinwoner"
    assert component_for_host_label("unknown") is None
