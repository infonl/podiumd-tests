"""Unit tests for the zgw_consumers Service checks."""

import pytest

from podiumd_tests import zgw_services
from podiumd_tests.zgw_services import SERVICE_REFERENCES
from podiumd_tests.zgw_services import ServiceReference
from podiumd_tests.zgw_services import list_path
from podiumd_tests.zgw_services import reference_problems
from podiumd_tests.zgw_services import service_problem
from podiumd_tests.zgw_services import service_problems


@pytest.mark.parametrize(
    ("api_root", "path"),
    [
        ("https://openzaak.local/zaken/api/v1/", "statussen"),
        ("https://openklant.kees00.example.nl/klantinteracties/api/v1/", "partijen"),
        ("https://objecten.local/api/v2/", "objects"),
        ("https://test-objecttypen.example.nl/api/v2/", "objecttypes"),
        ("https://notificaties.kees00.example.nl/api/v1/", "kanaal"),
        ("https://selectielijst.openzaak.nl/api/v1/", None),
        ("http://frankgateway-outway:9080/haalcentraal/api/brp/", None),
    ],
)
def test_list_path_by_api_path_else_host(api_root, path):
    assert list_path(api_root) == path


def service(api_root, status, auth_type="zgw", uuid="u1", *, referenced=True):
    return {
        "uuid": uuid,
        "name": "s1",
        "api_root": api_root,
        "auth_type": auth_type,
        "referenced": referenced,
        "status": status,
    }


@pytest.mark.parametrize(
    ("api_root", "path", "status", "problem"),
    [
        ("https://objecten.local/api/v2/", "objects", 200, None),
        ("https://objecten.local/api/v2/", "objects", 401, "s1 https://objecten.local/api/v2/objects (zgw): 401, "),
        ("https://objecten.local/api/v2/", "objects", "ConnectionError", "ConnectionError, expected 2xx"),
        ("https://openzaak.local/new/api/v1/", None, 200, "no list endpoint for this API in LIST_PATHS"),
        ("https://selectielijst.openzaak.nl/api/v1/", None, 404, None),
        ("https://selectielijst.openzaak.nl/api/v1/", None, 502, "502, expected an answer below 500"),
        ("https://selectielijst.openzaak.nl/api/v1/", None, "Timeout", "Timeout, expected an answer below 500"),
        # The BRP API behind api-proxy only takes POST.
        ("http://api-proxy/haalcentraal/api/brp/", None, 405, None),
        ("http://api-proxy/haalcentraal/api/brp/", None, 503, "503, expected an answer below 500"),
    ],
)
def test_service_problem(api_root, path, status, problem):
    found = service_problem(service(api_root, status), path)
    assert found == problem if problem is None else problem in str(found)


def test_service_problems_probe_each_referenced_service_on_its_list_path(page_env):
    env = page_env(zgw_services)
    unused = service("https://openzaak.local/autorisaties/api/v1/", 403, uuid="u2", referenced=False)
    env.snippet_result = [service("https://openzaak.local/zaken/api/v1/", 403), unused]
    assert service_problems(env, "openformulieren") == [
        "s1 https://openzaak.local/zaken/api/v1/statussen (zgw): 403, expected 2xx with its credentials"
    ]
    assert env.snippets == [
        ("openformulieren", "zgw_services", {"probes": {}, "used": []}),
        ("openformulieren", "zgw_services", {"probes": {"u1": "statussen"}, "used": []}),
    ]


def test_services_used_by_type_count_as_referenced(page_env):
    env = page_env(zgw_services)
    env.snippet_result = []
    service_problems(env, "openbeheer")
    assert env.snippets[0][2]["used"] == [{"api_type": "ztc"}]


def test_reference_problems_name_missing_rows_and_unset_fields(page_env, monkeypatch):
    references = (
        ServiceReference("config.APIConfig", "objecttypen_api_service"),
        ServiceReference("objects_api.ObjectsAPIGroupConfig", "objects_service"),
        ServiceReference("zgw_consumers.Service", where=(("api_type", "ztc"),)),
    )
    monkeypatch.setitem(SERVICE_REFERENCES, "openbeheer", references)
    env = page_env(zgw_services)
    env.snippet_result = [["objecttypen"], [None, "objecten"], []]
    assert reference_problems(env, "openbeheer") == [
        "objects_api.ObjectsAPIGroupConfig.objects_service: unset in 1 of 2 rows",
        "zgw_consumers.Service api_type=ztc: no rows",
    ]
    assert env.snippets[0][2]["references"][2] == {
        "model": "zgw_consumers.Service",
        "field": "",
        "where": {"api_type": "ztc"},
    }
