"""PodiumD runs, logs and stores time in UTC (hosting standard COMP004); users see their local time."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.defects import DefectSymptomError
from podiumd_tests.defects import symptom
from podiumd_tests.hygiene import UTC_NAMES
from podiumd_tests.hygiene import clock_offset
from podiumd_tests.hygiene import database_time_zone
from podiumd_tests.hygiene import hosting_scope
from podiumd_tests.hygiene import is_hosted_component
from podiumd_tests.kube import metadata_name

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.component,
    pytest.mark.requires("cluster"),
    pytest.mark.source(
        "hosting COMP004-timezone", "For logging and monitoring purposes, the timezone for applications should be UTC."
    ),
]


@pytest.mark.xfail(
    strict=True,
    raises=DefectSymptomError,
    reason="[zac-48] ZAC's chart sets TZ=Europe/Amsterdam (configmap zac), so ZAC runs and logs at +0100 or +0200;"
    " not reported upstream",
)
@pytest.mark.scenario("""
    When the clock of every PodiumD container is read
    Then each runs at UTC
""")
def test_containers_run_in_utc(podiumd_env: Environment) -> None:
    """The first container of every PodiumD workload reports offset +0000; containers without date are left out."""
    workloads, _ = hosting_scope(podiumd_env, [podiumd_env.profile.kube.namespace])
    offsets = {metadata_name(w): clock_offset(podiumd_env, w) for w in workloads if is_hosted_component(w)}
    other = {name: offset for name, offset in offsets.items() if offset not in {None, "+0000"}}
    assert {name: offset for name, offset in other.items() if name != "zac"} == {}
    with symptom():
        assert other == {}


@pytest.mark.requires("openzaak")
@pytest.mark.scenario("""
    When a new database session of Open Zaak starts
    Then its time zone is UTC
""")
def test_database_time_zone_is_utc(podiumd_env: Environment) -> None:
    """PostgreSQL's time zone for Open Zaak's sessions, before Django sets its own, is UTC."""
    assert database_time_zone(podiumd_env) in UTC_NAMES
