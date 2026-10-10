"""Write docs/draaiboek-coverage.md: which podiumd-tests test covers each case of the PodiumD test draaiboek.

The draaiboek is TA's test-catalog/cases.yaml (the Excel "Testscript PodiumD 4.6", 546 cases, class
A automatable, B with a mock, C manual, N placeholder). A case is linked to TA specs by the catalog's
poc_dekking and by the draaiboek rows TA's specs cite ("Portaal r54"); MIGRATION.md then says where
each TA spec went. podiumd-tests' own tests name their cases with @pytest.mark.tc("OF-001") (PLAN R15).
Run: python -m podiumd_tests.draaiboek <path to TA test-automation>.
"""

from __future__ import annotations

import ast
import re
import sys

from collections import Counter
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from podiumd_tests.config import REPO_ROOT

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
CITATION = re.compile(r"\b(" + "|".join(CITED_SHEETS) + r")[- ]r(\d+)\b")
TEST_FILE = re.compile(r"\btest_\w+\.py\b")
ROW = re.compile(r"^\| `([^`]+)` \|[^|]*\|[^|]*\| (\w+) \| (.*) \|$")
REASON_ROW = re.compile(r"^\| ([A-Z]+-\d+(?:, [A-Z]+-\d+)*) \| (.*) \|$")


def _section(name: str) -> list[str]:
    """The lines of a MIGRATION.md section."""
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
    return {Path(m[1]).name: (m[2], m[3]) for line in _section("TA") if (m := ROW.match(line))}


def out_of_scope() -> dict[str, str]:
    """Case id -> why no test covers it, from MIGRATION.md's Draaiboek section."""
    return {case: m[2] for line in _section("Draaiboek") if (m := REASON_ROW.match(line)) for case in m[1].split(", ")}


def cited(tests: Path) -> dict[tuple[str, int], set[str]]:
    """(sheet, Excel row) -> the TA spec files that cite it."""
    found: dict[tuple[str, int], set[str]] = defaultdict(set)
    for spec in tests.rglob("*.spec.ts"):
        for prefix, row in CITATION.findall(spec.read_text(encoding="utf-8")):
            found[CITED_SHEETS[prefix], int(row)].add(spec.name)
    return found


def _tc_ids(node: ast.AST) -> list[str]:
    """The case ids of a pytest.mark.tc(...) call, or none for any other expression."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "tc":
        return [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return []


def marked(tests: Path) -> dict[str, set[str]]:
    """Case id -> the tests ("path::function") marked with @pytest.mark.tc for it (also through pytestmark)."""
    found: dict[str, set[str]] = defaultdict(set)
    for path in sorted(tests.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_ids: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in node.targets):
                values = node.value.elts if isinstance(node.value, ast.List) else [node.value]
                module_ids += [i for v in values for i in _tc_ids(v)]
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        for function in functions:
            # Also the marks of pytest.param(...) in a parametrize decorator.
            ids = module_ids + [i for d in function.decorator_list for n in ast.walk(d) for i in _tc_ids(n)]
            for case in ids:
                found[case].add(f"{path.relative_to(tests.parent).as_posix()}::{function.name}")
    return found


def status(specs: set[str], decisions: dict[str, tuple[str, str]]) -> str:
    """covered, blocked or dropped, from the decisions of the case's TA specs; "" without any."""
    kinds = {decisions.get(s, ("unknown", ""))[0] for s in specs}
    if kinds & {"port", "merge", "replace"}:
        return "covered"
    if "todo" in kinds:
        return "blocked"
    return "dropped" if kinds else ""


def report_row(
    case: dict[str, Any], specs: set[str], decisions: dict[str, tuple[str, str]], own: set[str], reason: str
) -> tuple[str, str]:
    """The case's status and its report row; reason: why no test covers it, or ""."""
    state = "covered" if own else status(specs, decisions)
    if not state and reason:
        state = "out of scope"
    state = state or ("not covered" if case["klasse"] in {"A", "B"} else "out of scope")
    notes = " ".join(decisions[s][1] for s in specs if s in decisions and decisions[s][0] != "drop")
    names = set(TEST_FILE.findall(notes)) | {t.split("::")[1] for t in own}
    where = ", ".join(f"`{name}`" for name in sorted(names)) or (reason if state == "out of scope" else "")
    text = re.sub(r"\s+", " ", str(case["sub"] or case["proces"])).replace("|", "/").replace("<", "&lt;")[:110]
    return state, f"| {case['test_id']} | {case['klasse']} | {state} | {text} | {where} |"


def main(ta: Path) -> None:
    """Write the report."""
    catalog = yaml.safe_load((ta / "test-catalog" / "cases.yaml").read_text(encoding="utf-8"))
    decisions = migration()
    reasons = out_of_scope()
    citations = cited(ta / "tests")
    tests = marked(REPO_ROOT / "tests")
    rows: list[str] = []
    totals: dict[str, Counter[str]] = defaultdict(Counter)
    for case in catalog["cases"]:
        specs = {p.split(":")[0] for p in case["poc_dekking"]} | citations.get(
            (case["sheet"], case["excel_rij"]), set()
        )
        state, row = report_row(
            case, specs, decisions, tests.get(case["test_id"], set()), reasons.get(case["test_id"], "")
        )
        totals[case["klasse"]][state] += 1
        rows.append(row)
    states = ("covered", "blocked", "dropped", "not covered", "out of scope")
    summary = ["| Class | " + " | ".join(states) + " |", "|---|" + "---|" * len(states)]
    summary += [f"| {k} | " + " | ".join(str(totals[k][s]) for s in states) + " |" for k in sorted(totals)]
    out = REPO_ROOT / "docs" / "draaiboek-coverage.md"
    out.write_text(
        "# Draaiboek coverage\n\n"
        "Generated by `python -m podiumd_tests.draaiboek` from TA's test-catalog (draaiboek PodiumD 4.6, "
        "546 cases), `MIGRATION.md` and the tests' `@pytest.mark.tc` markers. Class A: automatable, B: with a "
        "mock, C: manual, N: placeholder. A case is covered when a test is marked with it, or when a TA spec "
        "that covered it (catalog mapping or a row the spec cites) was ported or merged. Why an A or B case "
        "is out of scope: `MIGRATION.md`, section Draaiboek.\n\n"
        + "\n".join(summary)
        + "\n\n| Case | Class | Status | Draaiboek | podiumd-tests |\n|---|---|---|---|---|\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
