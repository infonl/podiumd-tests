"""Unit tests for canonical component names and their host and deployment aliases."""

import pytest

from podiumd_tests.components import component_for_host
from podiumd_tests.components import deployed_components


def test_deployment_aliases():
    names = ["notificaties-celery", "openzaak", "podiumd-minikube-grafana", "kiss-frontend"]
    assert deployed_components(names) == {"opennotificaties", "openzaak", "grafana", "kiss"}


@pytest.mark.parametrize(
    ("host", "component"),
    [
        ("contact.kees00.pd.test-rig.nl", "kiss"),
        ("ontw-mijn.dimpact.icatt.nl", "openinwoner"),
        ("test-openzaak.dimpact.nl", "openzaak"),
        ("openformulieren-nginx.local", "openformulieren"),
        ("ontw-office-addin.dimpact.nl", "zgw-office-addin"),
        ("office-addin.local", "zgw-office-addin"),
        ("apisix-admin.kees00.pd.test-rig.nl", None),
        ("unknown.local", None),
    ],
)
def test_component_for_host(host, component):
    assert component_for_host(host) == component


def test_kiss_deployed_under_its_chart_name_contact():
    assert deployed_components(["contact-web", "ita-web"]) == {"kiss", "ita"}


def test_new_410_components_by_deployment():
    names = ["openvtb", "podiumd-zaakbrug", "zgw-office-addin-frontend", "zgw-office-addin-backend"]
    assert deployed_components(names) == {"openvtb", "zaakbrug", "zgw-office-addin"}
