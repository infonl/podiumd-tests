"""Unit tests for safe JSON reading."""

import pytest

from podiumd_tests.json_data import differences
from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.json_data import strings


def test_section_gives_an_empty_object_for_other_shapes():
    item = {"metadata": {"name": "zac"}, "spec": None, "status": ["x"]}
    assert section(item, "metadata") == {"name": "zac"}
    assert section(item, "spec") == {}
    assert section(item, "status") == {}
    assert section(item, "missing") == {}


def test_entries_and_strings_keep_only_their_type():
    mixed = [{"host": "a"}, "b", 3, None, {"host": "c"}]
    assert entries(mixed) == [{"host": "a"}, {"host": "c"}]
    assert strings(mixed) == ["b"]
    assert entries({"not": "a list"}) == []
    assert strings(None) == []


@pytest.mark.parametrize(
    ("wanted", "found", "expected"),
    [
        ({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}, []),
        ({"a": 1, "b": {"c": 2}}, {"a": 2, "b": {"c": 3}}, ["a", "b.c"]),
        ({"a": {"c": 2}}, {"a": None}, ["a"]),
        ({"l": [{"x": 1}, {"x": 2}]}, {"l": [{"x": 2, "id": 9}, {"x": 1, "id": 8}]}, []),
        ({"l": [{"x": 1}, {"x": 3}]}, {"l": [{"x": 1}]}, ["l[1]"]),
        ({"l": [1]}, {"l": "1"}, ["l[0]"]),
    ],
)
def test_differences_lists_the_paths_found_lacks(wanted, found, expected):
    assert differences(wanted, found) == expected
