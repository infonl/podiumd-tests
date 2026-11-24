"""Known upgrade hazards as rules over an estate profile, each with what the estate's owner does before upgrading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.auth.master_otp import CONDITIONAL
from podiumd_tests.auth.master_otp import DISABLED
from podiumd_tests.auth.master_otp import REQUIRED
from podiumd_tests.estate_profile import ABSENT
from podiumd_tests.estate_profile import PRESENT
from podiumd_tests.estate_profile import master_value
from podiumd_tests.json_data import section

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Sequence

    from podiumd_tests.json_data import JsonObject

type Version = tuple[int, ...]

ACTION = "action needed"
OK = "ok"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Rule:
    """One known hazard: when it applies, how to tell from a profile, and what to do."""

    id: str
    known_issue: str
    # Target podiumd chart versions it applies to: from lowest up to, not including, below; None is open.
    lowest: Version | None
    below: Version | None
    # ACTION, OK or UNKNOWN for a profile.
    condition: Callable[[JsonObject], str]
    action: str
    # What to find out when the profile cannot tell.
    unknown_action: str

    def is_applicable(self, target: Version | None) -> bool:
        """Whether an upgrade to target can meet the hazard; any target when None."""
        if target is None:
            return True
        is_above = self.lowest is None or target >= self.lowest
        return is_above and (self.below is None or target < self.below)


@dataclass(frozen=True)
class Finding:
    """A rule's verdict on one profile."""

    rule: Rule
    status: str
    action: str


def _operator_client_under_otp(profile: JsonObject) -> str:
    otp = master_value(profile, "direct_grant_otp")
    operator = master_value(profile, "operator_client")
    if otp == REQUIRED and operator == ABSENT:
        return ACTION
    if otp in {CONDITIONAL, DISABLED} or operator == PRESENT:
        return OK
    return UNKNOWN


RULES = (
    Rule(
        id="keycloak-operator-client-under-master-otp",
        known_issue="podiumd-chart-55",
        # Not fixed in any chart version yet.
        lowest=None,
        below=None,
        condition=_operator_client_under_otp,
        action=(
            "before upgrading: create the keycloak-operator service-account client in master, or make the direct"
            " grant OTP conditional during the rollout"
        ),
        unknown_action="check master's direct grant flow and whether the keycloak-operator client exists",
    ),
)


def evaluate(profile: JsonObject, target: Version | None, rules: Sequence[Rule] = RULES) -> list[Finding]:
    """Return each rule's finding on the profile for an upgrade to target."""
    findings: list[Finding] = []
    for rule in rules:
        if not rule.is_applicable(target):
            findings.append(Finding(rule, OK, "does not apply to this target"))
            continue
        status = rule.condition(profile)
        action = {ACTION: rule.action, UNKNOWN: rule.unknown_action}.get(status, "none")
        findings.append(Finding(rule, status, action))
    return findings


def is_action_needed(findings: Sequence[Finding]) -> bool:
    """Whether a finding asks for an action or for missing facts."""
    return any(finding.status != OK for finding in findings)


def open_issues(findings: Sequence[Finding]) -> str:
    """Return the known issues of the findings that are not ok, e.g. "podiumd-chart-55 (unknown)", or "none"."""
    found = [f"{finding.rule.known_issue} ({finding.status})" for finding in findings if finding.status != OK]
    return ", ".join(found) or "none"


def report(profile: JsonObject, findings: Sequence[Finding], target: str | None) -> str:
    """Return the findings as Markdown for the estate's owner."""
    chart = section(profile, "chart").get("podiumd", "unknown")
    lines = [
        f"# Upgrade actions: {profile.get('env', profile.get('estate'))}",
        "",
        f"Profile of {profile.get('exported_at', 'unknown date')}, podiumd chart {chart}, target {target or 'any'}.",
        "",
        "| finding | known issue | status | action |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| {finding.rule.id} | {finding.rule.known_issue} | {finding.status} | {finding.action} |"
        for finding in findings
    ]
    return "\n".join([*lines, ""])
