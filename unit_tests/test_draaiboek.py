"""Unit tests for linking draaiboek cases to TA specs and their MIGRATION.md decisions."""

import yaml

from podiumd_tests import draaiboek
from podiumd_tests.draaiboek import cited
from podiumd_tests.draaiboek import marked
from podiumd_tests.draaiboek import migration
from podiumd_tests.draaiboek import out_of_scope
from podiumd_tests.draaiboek import report_row
from podiumd_tests.draaiboek import status

DECISIONS = {"a.spec.ts": ("port", "x"), "b.spec.ts": ("todo", "y"), "c.spec.ts": ("drop", "z")}


def test_status_takes_the_best_decision_of_the_case_specs():
    assert status({"a.spec.ts", "b.spec.ts"}, DECISIONS) == "covered"
    assert status({"b.spec.ts", "c.spec.ts"}, DECISIONS) == "blocked"
    assert status({"c.spec.ts"}, DECISIONS) == "dropped"
    assert status(set(), DECISIONS) == ""


def test_cited_rows_map_to_their_sheet(tmp_path):
    (tmp_path / "x.spec.ts").write_text('test("Contact r19 and AK-r10", () => {});\n', encoding="utf-8")
    assert cited(tmp_path) == {
        ("Functionele tests Contact", 19): {"x.spec.ts"},
        ("Tests tbv Architectuurkaders", 10): {"x.spec.ts"},
    }


def test_migration_reads_the_ta_rows():
    decisions = migration()
    assert decisions["02-zaak-creatie.spec.ts"][0] == "port"


def test_tc_markers_of_functions_and_modules_are_found(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        'import pytest\npytestmark = [pytest.mark.ui, pytest.mark.tc("OF-001")]\n\n'
        '@pytest.mark.tc("OF-002", "OF-003")\ndef test_a():\n    pass\n\ndef test_b():\n    pass\n\n'
        '@pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.tc("OF-004"))])\ndef test_c(x):\n    pass\n',
        encoding="utf-8",
    )
    found = marked(tests)
    assert found["OF-001"] == {"tests/test_x.py::test_a", "tests/test_x.py::test_b", "tests/test_x.py::test_c"}
    assert found["OF-003"] == {"tests/test_x.py::test_a"}
    assert found["OF-004"] == {"tests/test_x.py::test_c"}


def test_out_of_scope_reads_the_draaiboek_reasons():
    reasons = out_of_scope()
    assert reasons["OI-022"] == reasons["KI-021"] == "eSuite, outside PodiumD"
    assert "ARCH-011" not in reasons


def test_a_reason_makes_an_uncovered_case_out_of_scope_but_never_hides_a_test():
    case = {"test_id": "OF-066", "klasse": "A", "sub": "Verwijderen", "proces": ""}
    assert (
        report_row(case, set(), DECISIONS, set(), "unclear")[1]
        == "| OF-066 | A | out of scope | Verwijderen | unclear |"
    )
    assert report_row(case, set(), DECISIONS, set(), "")[0] == "not covered"
    assert report_row(case, set(), DECISIONS, {"tests/test_x.py::test_a"}, "unclear")[0] == "covered"


def test_main_writes_the_report_with_totals_per_class(tmp_path, monkeypatch, capsys):
    ta = tmp_path / "ta"
    (ta / "test-catalog").mkdir(parents=True)
    (ta / "tests").mkdir()
    (ta / "tests" / "b.spec.ts").write_text('test("ZAC r7", () => {});\n', encoding="utf-8")
    case = {"sheet": "Functionele tests ZAC", "sub": "Zaak | aanmaken", "proces": "", "poc_dekking": []}
    cases = [
        {**case, "test_id": "ZAC-1", "klasse": "A", "excel_rij": 7},
        {**case, "test_id": "ZAC-2", "klasse": "A", "excel_rij": 8, "poc_dekking": ["a.spec.ts:3"]},
        {**case, "test_id": "ZAC-3", "klasse": "C", "excel_rij": 9},
    ]
    (ta / "test-catalog" / "cases.yaml").write_text(yaml.safe_dump({"cases": cases}), encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "tests").mkdir()
    monkeypatch.setattr(draaiboek, "REPO_ROOT", repo)
    monkeypatch.setattr(draaiboek, "migration", lambda: DECISIONS)
    monkeypatch.setattr(draaiboek, "out_of_scope", dict)
    draaiboek.main(ta)
    report = (repo / "docs" / "draaiboek-coverage.md").read_text(encoding="utf-8")
    assert "| A | 1 | 1 | 0 | 0 | 0 |" in report
    assert "| C | 0 | 0 | 0 | 0 | 1 |" in report
    assert "| ZAC-1 | A | blocked | Zaak / aanmaken |  |" in report
    assert capsys.readouterr().out.strip() == str(repo / "docs" / "draaiboek-coverage.md")
