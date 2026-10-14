"""Unit tests for the retry of navigations that a host network change aborted."""

from typing import TYPE_CHECKING
from typing import cast

import pytest

from playwright.sync_api import Error as PlaywrightError

from podiumd_tests.browser import NETWORK_CHANGED
from podiumd_tests.browser import guard_navigation
from podiumd_tests.browser import retry_network_change

if TYPE_CHECKING:
    from playwright.sync_api import Page


class FakePage:
    def __init__(self, *errors):
        self.errors = list(errors)
        self.pauses = 0
        self.url = "https://app.example.test/"

    def goto(self, url, **_kw):
        if self.errors:
            raise PlaywrightError(self.errors.pop(0))
        return url

    def reload(self, **_kw):
        return self.goto(self.url)

    def wait_for_timeout(self, _ms):
        self.pauses += 1


def test_goto_is_repeated_after_a_network_change_and_warns():
    fake = FakePage(f"Page.goto: {NETWORK_CHANGED} at x")
    page = guard_navigation(cast("Page", fake))
    with pytest.warns(UserWarning, match="retry 1 of 2"):
        assert page.goto("https://app.example.test/a") == "https://app.example.test/a"
    assert fake.pauses == 1


def test_other_errors_and_a_third_network_change_are_raised():
    with pytest.raises(PlaywrightError, match="ERR_CONNECTION_REFUSED"):
        guard_navigation(cast("Page", FakePage("net::ERR_CONNECTION_REFUSED"))).goto("https://x.test/")
    fake = FakePage(*[NETWORK_CHANGED] * 3)
    with pytest.warns(UserWarning, match="retry 2 of 2"), pytest.raises(PlaywrightError):
        retry_network_change(cast("Page", fake), lambda: fake.goto("https://x.test/"), "goto")
    assert fake.pauses == 2
