"""Unit tests for the shared response helpers."""

from http import HTTPStatus

import pytest
import requests

from podiumd_tests.responses import REFUSED
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.responses import get_entries
from podiumd_tests.responses import invalid_codes
from podiumd_tests.responses import invalid_names
from podiumd_tests.responses import is_root_answering
from podiumd_tests.responses import is_server_error
from podiumd_tests.responses import root_problem
from podiumd_tests.responses import url_host


def test_expect_status_returns_the_response(response_factory):
    response = response_factory(status=401)
    assert expect_status(response, *REFUSED) is response


def test_expect_status_names_method_url_and_expectation(response_factory):
    response = response_factory(status=200, url="https://oz.example.test/zaken")
    response.request = requests.Request("POST", response.url).prepare()
    with pytest.raises(
        UnexpectedStatusError, match=r"^POST https://oz\.example\.test/zaken: HTTP 200, expected 401 or 403$"
    ):
        expect_status(response, HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN)


def test_describe_without_request_assumes_get(response_factory):
    assert describe(response_factory(status=404, url="https://x.test/")) == "GET https://x.test/: HTTP 404"


@pytest.mark.parametrize(("status", "expected"), [(200, False), (403, False), (499, False), (500, True), (503, True)])
def test_is_server_error(response_factory, status, expected):
    assert is_server_error(response_factory(status=status)) is expected


@pytest.mark.parametrize(
    ("url", "host"), [("https://zac.local:8443/x", "zac.local"), ("http://ZAC.local", "zac.local"), ("not a url", "")]
)
def test_url_host(url, host):
    assert url_host(url) == host


def test_get_entries_reads_an_array_or_results_or_items(fake_http):
    fake_http(
        {"/a": (200, [{"id": 1}, "x"]), "/r": (200, {"results": [{"id": 2}]}), "/i": (200, {"items": [{"id": 3}]})}
    )
    http = requests.Session()
    assert [get_entries(http, f"https://x.test/{p}") for p in ("a", "r", "i")] == [
        [{"id": 1}],
        [{"id": 2}],
        [{"id": 3}],
    ]


def test_get_entries_needs_200(fake_http):
    fake_http({"/a": (403, {"detail": "no"})})
    with pytest.raises(UnexpectedStatusError):
        get_entries(requests.Session(), "https://x.test/a")


@pytest.mark.parametrize(("status", "problem"), [(200, None), (401, None), (502, "HTTP 502")])
def test_root_answers_unless_the_component_fails(fake_http, status, problem):
    sent = fake_http({"/": (status, {})})
    assert root_problem(requests.Session(), "https://zac.example.test", 5) == problem
    assert is_root_answering(requests.Session(), "https://zac.example.test", 5) is (problem is None)
    assert sent[0].url == "https://zac.example.test/"


def test_a_refused_connection_is_no_answer(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise requests.ConnectionError

    monkeypatch.setattr(requests.Session, "get", refuse)
    assert root_problem(requests.Session(), "https://zac.example.test", 5) == "ConnectionError"
    assert is_root_answering(requests.Session(), "https://zac.example.test", 5) is False


def test_invalid_codes_and_names(response_factory):
    params = [{"name": "zaaktype", "code": "bad-url"}, {"name": "nonFieldErrors", "code": "zaaktype-mismatch"}]
    response = response_factory(status=400, json_body={"invalidParams": params})
    assert invalid_codes(response) == ["bad-url", "zaaktype-mismatch"]
    assert invalid_names(response) == {"zaaktype", "nonFieldErrors"}
    open_object = response_factory(status=400, json_body={"invalid_params": params[:1]})
    assert invalid_codes(open_object) == ["bad-url"]
