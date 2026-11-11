"""Unit tests for the test overview."""

from podiumd_tests import overview
from podiumd_tests.overview import Case


def _case(
    *,
    tier="component",
    area="zac",
    function="test_zac.py::test_a",
    origins=("podiumd-tests",),
    known_issues=(),
    has_scenario=True,
    destructive=False,
):
    return Case(tier, area, function, origins, known_issues, has_scenario, destructive)


def test_area_is_the_directory_under_the_tier_or_the_module():
    assert overview.area_of(("tests", "component", "zac", "test_zac_zaak.py")) == "zac"
    assert overview.area_of(("tests", "smoke", "test_api_health.py")) == "api_health"


def test_known_issues_sort_by_their_number():
    assert sorted(["open-zaak-10", "open-zaak-2", "kiss-1"], key=overview.issue_key) == [
        "kiss-1",
        "open-zaak-2",
        "open-zaak-10",
    ]


def test_render_counts_cases_functions_and_expected_failures():
    cases = [
        _case(),
        _case(function="test_zac.py::test_b", known_issues=("zac-10",)),
        _case(function="test_zac.py::test_b"),
        _case(tier="smoke", area="api_health", function="test_api_health.py::test_c", origins=()),
        _case(function="test_zac.py::test_d", destructive=True, has_scenario=False),
    ]
    text = overview.render(cases, unit_tests=7, perf_endpoints=3)
    assert "| smoke | 1 | 1 | 0 |" in text
    assert "| component | 4 | 3 | 1 |" in text
    assert "| **full tier** | **4** | **3** |  |" in text
    assert "| zac-10 | 1 |" in text
    assert "| - | 1 |" in text
    assert "Unit tests (`unit_tests/`, functions): 7. Perf endpoints (`perf/runs.py`): 3." in text
    assert "Tests without a scenario: 1." in text


def test_unit_test_count_counts_test_functions(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "def test_one():\n    pass\n\ndef helper():\n    pass\n\nclass X:\n    def test_two(self):\n        pass\n"
    )
    (tmp_path / "other.py").write_text("def test_ignored():\n    pass\n")
    assert overview.unit_test_count(tmp_path) == 2


def test_check_reports_an_out_of_date_overview(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(overview, "OUT", tmp_path / "test-overview.md")
    monkeypatch.setattr(overview, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(overview, "collect", lambda: [_case()])
    monkeypatch.setattr(overview, "unit_test_count", lambda _: 1)
    (tmp_path / "test-overview.md").write_text("old\n")
    assert overview.main(["--check"]) == 1
    assert "out of date" in capsys.readouterr().out
    assert overview.main([]) == 0
    assert overview.main(["--check"]) == 0
