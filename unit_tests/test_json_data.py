"""Unit tests for safe JSON reading."""

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
