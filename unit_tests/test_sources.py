"""Unit tests for the source marker checks."""

import pytest

from podiumd_tests.sources import source_problems


class FakeItem:
    nodeid = "t.py::test_x"

    def __init__(self, *markers):
        self.markers = markers

    def iter_markers(self, _name):
        return iter(self.markers)


@pytest.mark.parametrize(
    ("markers", "problem"),
    [
        ((), "no @pytest.mark.source(origin, reason)"),
        ((pytest.mark.source("TA x.spec.ts").mark,), "source needs two texts"),
        ((pytest.mark.source("TA x.spec.ts", " ").mark,), "source needs two texts"),
        ((pytest.mark.source("TA x.spec.ts", "why").mark,), None),
    ],
)
def test_source_problems(markers, problem):
    found = source_problems(FakeItem(*markers))  # pyright: ignore[reportArgumentType]  # duck-typed pytest.Item
    assert found == ([] if problem is None else [found[0]])
    assert problem is None or problem in found[0]
