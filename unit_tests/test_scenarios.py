"""Unit tests for the scenario marker."""

import pytest

from podiumd_tests.scenarios import scenario
from podiumd_tests.scenarios import scenario_problems


class FakeItem:
    nodeid = "t.py::test_x"

    def __init__(self, text=None):
        self.marker = None if text is None else pytest.mark.scenario(text).mark

    def get_closest_marker(self, _name):
        return self.marker


GOOD = """
    Given a zaak in ZAC
    When the behandelaar opens the werkvoorraad
    Then the zaak is listed
    And its initiator is shown
"""


def test_scenario_is_dedented_and_stripped():
    assert scenario(FakeItem(GOOD)).splitlines()[0] == "Given a zaak in ZAC"  # pyright: ignore[reportArgumentType]
    assert scenario(FakeItem()) == ""  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (None, None),
        (GOOD, None),
        ("When it runs\nThen it works", None),
        ("Given a\nWhen b", "scenario has no Then"),
        ("Then it works", "scenario starts with 'Then', not Given or When"),
        ("Given a\nWhen b\nThen c\nSo d", "scenario line starts with none of Given, When, Then, And, But: 'So d'"),
    ],
)
def test_scenario_problems(text, problem):
    found = scenario_problems(FakeItem(text))  # pyright: ignore[reportArgumentType]  # duck-typed pytest.Item
    expected = [] if problem is None else [f"t.py::test_x: {problem}"]
    assert found == expected
