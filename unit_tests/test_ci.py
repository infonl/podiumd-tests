"""Unit tests for the CI runner integration: log groups, job summary and options from the environment."""

from podiumd_tests import cli
from podiumd_tests.ci import group
from podiumd_tests.ci import publish_summary
from podiumd_tests.ci import runner


def test_runner_is_detected_from_its_variables():
    assert runner({"GITHUB_ACTIONS": "true"}) == "github"
    assert runner({"TF_BUILD": "True"}) == "azure"
    assert runner({}) is None


def test_groups_print_the_runner_markers_only_on_a_runner(capsys):
    with group("pytest full", {"GITHUB_ACTIONS": "true"}):
        print("output")
    with group("pytest full", {}):
        print("plain")
    assert capsys.readouterr().out.splitlines() == ["::group::pytest full", "output", "::endgroup::", "plain"]


def test_summary_is_appended_to_the_github_step_summary(tmp_path):
    summary, step = tmp_path / "summary.md", tmp_path / "step"
    summary.write_text("# run\n", encoding="utf-8")
    publish_summary(summary, {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(step)})
    assert step.read_text(encoding="utf-8") == "# run\n\n"


def test_summary_is_uploaded_on_azure_devops(tmp_path, capsys):
    summary = tmp_path / "summary.md"
    summary.write_text("# run\n", encoding="utf-8")
    publish_summary(summary, {"TF_BUILD": "True"})
    assert capsys.readouterr().out.strip() == f"##vso[task.uploadsummary]{summary}"


def test_env_and_tier_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("PODIUMD_TESTS_ENV", "kees00")
    monkeypatch.setenv("PODIUMD_TESTS_TIER", "full")
    args = cli.build_parser().parse_args(["run"])
    assert (args.env, args.tier) == ("kees00", "full")
    assert cli.build_parser().parse_args(["run", "--env", "other"]).env == "other"
