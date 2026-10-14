"""kiss_register: which KISS register a klantcontact test may use."""

import pytest
import requests

from podiumd_tests.kcc import kiss_register

KISS = "https://kiss.example.test"


def test_kiss_register_sends_calls_to_the_default_open_klant_2_register(fake_http):
    fake_http(
        {
            "/api/environment/registers": (
                200,
                {
                    "systemen": [
                        {"identifier": "other", "isDefault": False, "registryVersion": "OpenKlant2"},
                        {"identifier": "ok2", "isDefault": True, "registryVersion": "OpenKlant2"},
                    ]
                },
            )
        }
    )
    assert kiss_register(requests.Session(), KISS) == {"systemIdentifier": "ok2"}


def test_kiss_register_skips_an_openklant1_default_register(fake_http):
    """An OpenKlant1 register goes through the podiumd-adapter to the e-Suite, not to Open Klant."""
    fake_http(
        {
            "/api/environment/registers": (
                200,
                {
                    "systemen": [
                        {"identifier": "http://podiumd-adapter", "isDefault": True, "registryVersion": "OpenKlant1"}
                    ]
                },
            )
        }
    )
    with pytest.raises(pytest.skip.Exception, match="OpenKlant1"):
        kiss_register(requests.Session(), KISS)
