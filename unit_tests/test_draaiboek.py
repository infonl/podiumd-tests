"""Unit tests for linking draaiboek cases to TA specs and their MIGRATION.md decisions."""

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
        '@pytest.mark.tc("OF-002", "OF-003")\ndef test_a():\n    pass\n\ndef test_b():\n    pass\n',
        encoding="utf-8",
    )
    found = marked(tests)
    assert found["OF-001"] == {"tests/test_x.py::test_a", "tests/test_x.py::test_b"}
    assert found["OF-003"] == {"tests/test_x.py::test_a"}


def test_out_of_scope_reads_the_draaiboek_reasons():
    reasons = out_of_scope()
    assert reasons["OI-022"] == reasons["KI-021"] == "eSuite, outside PodiumD"
    assert "ZAC-004" not in reasons


def test_a_reason_makes_an_uncovered_case_out_of_scope_but_never_hides_a_test():
    case = {"test_id": "OF-066", "klasse": "A", "sub": "Verwijderen", "proces": ""}
    assert (
        report_row(case, set(), DECISIONS, set(), "unclear")[1]
        == "| OF-066 | A | out of scope | Verwijderen | unclear |"
    )
    assert report_row(case, set(), DECISIONS, set(), "")[0] == "not covered"
    assert report_row(case, set(), DECISIONS, {"tests/test_x.py::test_a"}, "unclear")[0] == "covered"
