"""Unit tests for the layout of the environment tests."""

import ast

from collections import Counter

from podiumd_tests.config import REPO_ROOT


def test_environment_test_modules_have_unique_names():
    # tests/ has no packages: pytest refuses two modules with one basename in a run.
    names = Counter(p.name for p in (REPO_ROOT / "tests").rglob("test_*.py"))
    assert [n for n, count in names.items() if count > 1] == []


def _scenarios(node: ast.FunctionDef) -> int:
    return sum(
        1
        for d in node.decorator_list
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "scenario"
    )


def test_every_environment_test_has_one_scenario():
    # Collection checks a scenario's format; only the source can show one is missing or doubled.
    wrong = [
        f"{path.relative_to(REPO_ROOT)}::{node.name} has {_scenarios(node)}"
        for path in sorted((REPO_ROOT / "tests").rglob("test_*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_") and _scenarios(node) != 1
    ]
    assert wrong == []
