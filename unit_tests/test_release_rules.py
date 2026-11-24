"""Unit tests for the release rules over estate profiles."""

import pytest

from podiumd_tests import release_rules


def profile(**master):
    return {
        "env": "e",
        "exported_at": "2026-11-24T12:00:00+00:00",
        "chart": {"podiumd": "4.10.1"},
        "keycloak_master": master,
    }


@pytest.mark.parametrize(
    ("master", "status"),
    [
        ({"direct_grant_otp": "required", "operator_client": "absent"}, "action needed"),
        ({"direct_grant_otp": "required", "operator_client": "present"}, "ok"),
        ({"direct_grant_otp": "conditional", "operator_client": "absent"}, "ok"),
        ({"direct_grant_otp": "required", "operator_client": "unknown"}, "unknown"),
        ({}, "unknown"),
    ],
)
def test_the_operator_client_rule_needs_otp_required_and_the_client_absent(master, status):
    finding = release_rules.evaluate(profile(**master), None)[0]
    assert (finding.rule.known_issue, finding.status) == ("podiumd-chart-55", status)
    assert release_rules.is_action_needed([finding]) == (status != "ok")


def test_the_report_names_each_finding_with_its_action():
    findings = release_rules.evaluate(profile(direct_grant_otp="required", operator_client="absent"), (4, 11, 0))
    text = release_rules.report(profile(), findings, "4.11.0")
    assert "podiumd chart 4.10.1, target 4.11.0." in text
    assert "| podiumd-chart-55 | action needed | before upgrading: create the keycloak-operator" in text


def test_a_rule_outside_its_versions_is_ok():
    rule = release_rules.Rule("r", "x-1", (4, 9), (4, 12), lambda _profile: "action needed", "do", "find out")
    assert [finding.status for finding in release_rules.evaluate({}, (4, 12, 0), [rule])] == ["ok"]
    assert rule.is_applicable((4, 11, 3))
    assert not rule.is_applicable((4, 8))
