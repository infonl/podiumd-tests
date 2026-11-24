"""Unit tests for Frank!Gateway response checks."""

import pytest
import requests

from podiumd_tests.gateway import admin_routes
from podiumd_tests.gateway import brp_header_problems
from podiumd_tests.gateway import brp_routes_problems
from podiumd_tests.gateway import expected_brp_headers
from podiumd_tests.gateway import is_no_route
from podiumd_tests.gateway import kiss_brp_headers
from podiumd_tests.gateway import route_name
from podiumd_tests.gateway import wiring_problems


@pytest.mark.parametrize(
    ("status", "json_body", "body", "expected"),
    [
        (404, {"error_msg": "404 Route Not Found"}, b"", True),
        (404, {"error_msg": "kvk number unknown"}, b"", False),
        (404, None, b"<html>not found</html>", False),
        (404, ["route"], b"", False),
        (405, {"error_msg": "route"}, b"", False),
    ],
)
def test_is_no_route(response_factory, status, json_body, body, expected):
    assert is_no_route(response_factory(status=status, json_body=json_body, body=body)) is expected


OUTWAY = "http://frankgateway-outway.podiumd.svc.cluster.local:9080"
PROXY = "http://api-proxy.podiumd.svc.cluster.local"


def test_route_name_uses_the_apps_prefix():
    assert route_name("openinwoner", "brp") == "oip-brp"


def test_admin_routes_are_keyed_by_name(fake_http):
    routes = {"list": [{"value": {"name": "zac-brp", "uri": "/zac/brp/*"}}, {"value": {"name": "kiss-kvk"}}]}
    sent = fake_http({"GET /apisix/admin/routes": (200, routes)})
    found = admin_routes(requests.Session(), "http://127.0.0.1:9180", "viewer-key")
    assert sorted(found) == ["kiss-kvk", "zac-brp"]
    assert sent[0].headers["X-API-KEY"] == "viewer-key"


def test_kiss_brp_headers_leave_out_the_headers_per_request():
    config = {
        "HAAL_CENTRAAL_CUSTOM_HEADERS__x-request-application": "gem-acc-kiss-podiumd-contact",
        "HAAL_CENTRAAL_CUSTOM_HEADERS__x-doelbinding__RaadpleegMetBurgerservicenummer": "BRPACT-KISS",
        "KVK_BASE_URL": f"{OUTWAY}/kiss/kvk/api",
    }
    assert kiss_brp_headers(config) == {"x-request-application": "gem-acc-kiss-podiumd-contact"}


def test_expected_brp_headers_name_the_app():
    kiss = {"x-request-application": "gem-acc-kiss-podiumd-contact", "x-request-afnemerscode": "123456"}
    assert expected_brp_headers("openformulieren", kiss) == {
        "x-request-application": "gem-acc-forms-podiumd-contact",
        "x-request-afnemerscode": "123456",
    }


def brp_route(headers):
    return {"plugins": {"proxy-rewrite": {"headers": {"set": headers}}}}


def test_brp_header_problems_never_show_the_key():
    route = brp_route({"x-api-key": "s3cret", "x-request-application": "gem-acc-kiss-podiumd-contact"})
    problems = brp_header_problems("forms-brp", route, {"x-request-application": "gem-acc-forms-podiumd-contact"})
    assert problems == [
        "forms-brp: x-request-application is 'gem-acc-kiss-podiumd-contact', expected 'gem-acc-forms-podiumd-contact'"
    ]
    assert brp_header_problems("zac-brp", brp_route({}), {}) == ["zac-brp: sets no x-api-key"]


def test_brp_header_problems_are_empty_for_a_complete_route():
    assert brp_header_problems("zac-brp", brp_route({"x-api-key": "s3cret"}), {}) == []


@pytest.mark.parametrize(
    ("url", "registers_only", "problems"),
    [
        (f"{OUTWAY}/zac/brp", True, ()),
        (f"{OUTWAY}/zac", True, ()),
        (f"{PROXY}/brp", True, ("zac BRP {url}: on the api-proxy",)),
        (f"{OUTWAY}/kiss/brp", True, ("zac BRP {url}: on the outway, but not under /zac/",)),
        (f"{OUTWAY}/zacx/brp", False, ("zac BRP {url}: on the outway, but not under /zac/",)),
        ("https://api.kvk.nl/test", True, ("zac BRP {url}: not through the outway",)),
        ("https://openzaak.example.test/zaken/api/v1/", False, ()),
    ],
)
def test_wiring_problems(url, registers_only, problems):
    found = wiring_problems("zac", {"BRP": url}, OUTWAY, registers_only=registers_only)
    assert found == [problem.format(url=url) for problem in problems]


def test_brp_routes_problems_check_every_brp_route():
    routes = {
        "zac-brp": brp_route({"x-api-key": "s3cret"}),
        "forms-brp": brp_route({"x-api-key": "s3cret", "x-request-application": "gem-acc-forms-podiumd-contact"}),
        "oip-brp": brp_route({}),
        "zac-kvk": brp_route({}),
    }
    kiss = {"x-request-application": "gem-acc-kiss-podiumd-contact"}
    assert brp_routes_problems(routes, kiss) == [
        "oip-brp: sets no x-api-key",
        "oip-brp: x-request-application is None, expected 'gem-acc-oip-podiumd-contact'",
    ]


def test_brp_routes_problems_without_a_brp_route():
    assert brp_routes_problems({"zac-kvk": brp_route({})}, {}) == [
        "no BRP route in the outway (looked for zac-brp, kiss-brp, forms-brp, oip-brp)"
    ]
