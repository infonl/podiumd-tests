"""Unit tests for the layout of the environment tests."""

from collections import Counter

from podiumd_tests.config import REPO_ROOT


def test_environment_test_modules_have_unique_names():
    # tests/ has no packages: pytest refuses two modules with one basename in a run.
    names = Counter(p.name for p in (REPO_ROOT / "tests").rglob("test_*.py"))
    assert [n for n, count in names.items() if count > 1] == []
