"""Unit tests for canonical component names and their host and deployment aliases."""

import pytest

from podiumd_tests.components import component_for_host
from podiumd_tests.components import deployed_components


def test_deployment_aliases():
    names = ["notificaties-celery", "openzaak", "podiumd-grafana", "kiss-frontend"]
    assert deployed_components(names) == {"opennotificaties", "openzaak", "grafana", "kiss"}


@pytest.mark.parametrize(
    ("host", "component"),
    [
        ("contact.kees00.pd.test-rig.nl", "kiss"),
        ("ontw-mijn.dimpact.icatt.nl", "openinwoner"),
        ("test-openzaak.dimpact.nl", "openzaak"),
        ("openformulieren-nginx.local", "openformulieren"),
        ("apisix-admin.kees00.pd.test-rig.nl", None),
        ("unknown.local", None),
    ],
)
def test_component_for_host(host, component):
    assert component_for_host(host) == component
