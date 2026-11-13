"""Write docs/draaiboek-coverage.md: which podiumd-tests test covers each case of the PodiumD test draaiboek.

The draaiboek is TA's test-catalog/cases.yaml (the Excel "Testscript PodiumD 4.6", 546 cases, class
A automatable, B with a mock, C manual, N placeholder). A case is linked to TA specs by the catalog's
poc_dekking and by the draaiboek rows TA's specs cite ("Portaal r54"); MIGRATION.md then says where
each TA spec went. podiumd-tests' own tests name their cases with @pytest.mark.tc("OF-001").
Run: python -m podiumd_tests.draaiboek <path to TA test-automation>.
"""

from __future__ import annotations

import ast
import re
import sys

from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from podiumd_tests.config import REPO_ROOT

if TYPE_CHECKING:
    from collections.abc import Mapping

# How TA's specs name a draaiboek tab when they cite a row.
CITED_SHEETS = {
    "AK": "Tests tbv Architectuurkaders",
    "ABC": "Functionele tests ABC",
    "Contact": "Functionele tests Contact",
    "Continuïteit": "Continuïteit - Connectiviteit",
    "FB": "Functionele tests FB",
    "Formulier": "Functionele tests Formulier",
    "ITA": "Functionele tests ITA",
    "Portaal": "Functionele tests Portaal",
    "ZAC": "Functionele tests ZAC",
}
CITATION = re.compile(rf"\b({'|'.join(CITED_SHEETS)})[- ]r(\d+)\b")
TEST_FILE = re.compile(r"\btest_\w+\.py\b")
ROW = re.compile(r"^\| `([^`]+)` \|[^|]*\|[^|]*\| (\w+) \| (.*) \|$")
# TA spec file name -> (decision, notes).
Decisions = dict[str, tuple[str, str]]
REASON_ROW = re.compile(r"^\| ([A-Z]+-\d+(?:, [A-Z]+-\d+)*) \| (.*) \|$")


def _section(name: str) -> list[str]:
    """Return the lines of a MIGRATION.md section."""
    lines: list[str] = []
    current = ""
    for line in (REPO_ROOT / "MIGRATION.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
        elif current == name:
            lines.append(line)
    return lines


def migration() -> dict[str, tuple[str, str]]:
    """TA spec file name -> (decision, notes) from MIGRATION.md's TA section."""
    rows = (ROW.match(line) for line in _section("TA"))
    return {Path(match[1]).name: (match[2], match[3]) for match in rows if match}


def uncovered() -> dict[str, tuple[str, str]]:
    """Case id -> (status, reason) of a case no test shows: MIGRATION.md's sections Draaiboek and Draaiboek, waiting."""
    found: dict[str, tuple[str, str]] = {}
    for section, state in (("Draaiboek", "out of scope"), ("Draaiboek, waiting", "blocked")):
        for match in filter(None, (REASON_ROW.match(line) for line in _section(section))):
            found.update(dict.fromkeys(match[1].split(", "), (state, match[2])))
    return found


def cited(tests: Path) -> dict[tuple[str, int], set[str]]:
    """(sheet, Excel row) -> the TA spec files that cite it."""
    found: dict[tuple[str, int], set[str]] = defaultdict(set)
    for spec in tests.rglob("*.spec.ts"):
        for prefix, row in CITATION.findall(spec.read_text(encoding="utf-8")):
            found[CITED_SHEETS[prefix], int(row)].add(spec.name)
    return found


def _tc_ids(node: ast.AST) -> list[str]:
    """Return the case ids of a pytest.mark.tc(...) call, or none for any other expression."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "tc":
        return [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
    return []


def marked(tests: Path) -> dict[str, set[str]]:
    """Case id -> the tests ("path::function") marked with @pytest.mark.tc for it (also through pytestmark)."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(tests.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_ids = _module_ids(tree)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
        for function in functions:
            for case in module_ids + _function_ids(function):
                found[case].add(f"{path.relative_to(tests.parent).as_posix()}::{function.name}")
    return found


def _module_ids(tree: ast.Module) -> list[str]:
    """Return the case ids of the module's pytestmark."""
    ids: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_pytestmark_assignment(node):
            values = node.value.elts if isinstance(node.value, ast.List) else [node.value]
            ids += [case for value in values for case in _tc_ids(value)]
    return ids


def _is_pytestmark_assignment(node: ast.Assign) -> bool:
    return any(getattr(target, "id", "") == "pytestmark" for target in node.targets)


def _function_ids(function: ast.FunctionDef) -> list[str]:
    """Return the case ids of the test's decorators, also the marks of pytest.param(...) in a parametrize decorator."""
    decorator_nodes = [node for decorator in function.decorator_list for node in ast.walk(decorator)]
    return [case for node in decorator_nodes for case in _tc_ids(node)]


def status(specs: set[str], decisions: dict[str, tuple[str, str]]) -> str:
    """covered, blocked or dropped, from the decisions of the case's TA specs; "" without any."""
    kinds = {decisions.get(spec, ("unknown", ""))[0] for spec in specs}
    if kinds & {"port", "merge", "replace"}:
        return "covered"
    if "todo" in kinds:
        return "blocked"
    return "dropped" if kinds else ""


def _state(case: Mapping[str, object], specs: set[str], decisions: Decisions, reason: str) -> str:
    """Return the status of a case no test is marked with; a "blocked" reason outranks TA's citations."""
    if reason == "blocked":
        return reason
    found = status(specs, decisions) or reason
    if found:
        return found
    return "not covered" if case["klasse"] in {"A", "B"} else "out of scope"


def report_row(
    case: Mapping[str, object],
    specs: set[str],
    decisions: dict[str, tuple[str, str]],
    own: set[str],
    reason: tuple[str, str] = ("", ""),
) -> tuple[str, str]:
    """Return the case's status and its report row; reason: (status, why) from `uncovered`, or empty."""
    state = "covered" if own else _state(case, specs, decisions, reason[0])
    kept = [decisions[spec] for spec in specs if spec in decisions]
    notes = " ".join(note for decision, note in kept if decision != "drop")
    names = set(TEST_FILE.findall(notes)) | {test.split("::")[1] for test in own}
    where = ", ".join(f"`{name}`" for name in sorted(names))
    if state in {"blocked", "out of scope"} and reason[0] == state:
        where = reason[1]
    description = str(case["sub"] or case["proces"])
    text = re.sub(r"\s+", " ", description)
    text = text.replace("|", "/").replace("<", "&lt;")[:110]
    return state, f"| {case['test_id']} | {case['klasse']} | {state} | {text} | {where} |"


def main(ta: Path) -> None:
    """Write the report."""
    catalog = yaml.safe_load((ta / "test-catalog" / "cases.yaml").read_text(encoding="utf-8"))
    decisions = migration()
    reasons = uncovered()
    citations = cited(ta / "tests")
    tests = marked(REPO_ROOT / "tests")
    rows: list[str] = []
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for case in catalog["cases"]:
        specs = {coverage.split(":")[0] for coverage in case["poc_dekking"]} | citations.get(
            (case["sheet"], case["excel_rij"]), set()
        )
        state, row = report_row(
            case,
            specs,
            decisions,
            tests.get(case["test_id"], set()),
            reasons.get(case["test_id"], ("", "")),
        )
        totals[case["klasse"]][state] += 1
        rows.append(row)
    states = ("covered", "blocked", "dropped", "not covered", "out of scope")
    summary = [f"| Class | {' | '.join(states)} |", f"|---|{'---|' * len(states)}"]
    for klasse in sorted(totals):
        counts = " | ".join(str(totals[klasse][column]) for column in states)
        summary.append(f"| {klasse} | {counts} |")
    out = REPO_ROOT / "docs" / "draaiboek-coverage.md"
    out.write_text(
        "# Draaiboek coverage\n\n"
        "Generated by `python -m podiumd_tests.draaiboek` from TA's test-catalog (draaiboek PodiumD 4.6, "
        "546 cases), `MIGRATION.md` and the tests' `@pytest.mark.tc` markers. Class A: automatable, B: with a "
        "mock, C: manual, N: placeholder. A case is covered when a test is marked with it, or when a TA spec "
        "that covered it (catalog mapping or a row the spec cites) was ported or merged. Why an A or B case "
        "is out of scope: `MIGRATION.md`, section Draaiboek; what a blocked case waits for: its section "
        "Draaiboek, waiting.\n\n"
        + "\n".join(summary)
        + "\n\n| Case | Class | Status | Draaiboek | podiumd-tests |\n|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
