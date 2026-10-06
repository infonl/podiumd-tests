"""Unit tests for capability detection."""

from podiumd_tests.capabilities import detect


def test_profile_alone_decides_without_cluster(profile_factory):
    caps = detect(profile_factory(), None)
    assert caps.present == {"openzaak", "keycloak-admin"}
    assert caps.skip_reason("openzaak") is None
    assert caps.skip_reason("zac") == "requires: zac (no URL in profile)"
    assert caps.skip_reason("cluster") == "requires: cluster (kube API of context ctx not reachable from this console)"


def test_configured_but_not_deployed_is_absent(profile_factory):
    caps = detect(profile_factory(), ["keycloak-0"])
    # keycloak-admin has no deployment of its own, so its URL is enough.
    assert caps.present == {"keycloak-admin", "cluster"}
    assert caps.skip_reason("openzaak") == "requires: openzaak (no deployment in namespace podiumd)"
