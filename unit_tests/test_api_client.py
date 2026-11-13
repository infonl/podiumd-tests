"""Unit tests for ApiClient lists."""

import threading

import requests

from podiumd_tests.clients.api import ApiClient
from podiumd_tests.clients.api import per_thread

API = "https://api.example.test/v1"


def test_list_follows_next_pages(fake_http):
    fake_http(
        {
            "/v1/zaken": (200, {"results": [{"n": 1}], "next": f"{API}/zaken2"}),
            "/v1/zaken2": (200, {"results": [{"n": 2}], "next": None}),
        }
    )
    assert ApiClient(requests.Session(), API, {}).list("zaken") == [{"n": 1}, {"n": 2}]


def test_list_takes_a_plain_array(fake_http):
    fake_http({"/v1/zaakinformatieobjecten": (200, [{"n": 1}])})
    assert ApiClient(requests.Session(), API, {}).list("zaakinformatieobjecten") == [{"n": 1}]


def test_per_thread_makes_one_client_per_thread():
    made = []

    def make():
        made.append(1)
        return len(made)

    client = per_thread(make)
    assert client() == client() == 1
    other = []
    thread = threading.Thread(target=lambda: other.append(client()))
    thread.start()
    thread.join()
    assert other == [2]
