"""Unit tests for linking draaiboek cases to TA specs and their MIGRATION.md decisions."""

from podiumd_tests.draaiboek import cited
from podiumd_tests.draaiboek import migration
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
