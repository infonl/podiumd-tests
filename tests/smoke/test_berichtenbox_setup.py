"""Is the Berichtenbox (MOBB) chain set up where OMC reads Open VTB? Read-only.

The chain itself (a bericht through Open VTB, Open Notificaties and OMC to Notify) is in the integration tier:
tests/integration/test_omc_bericht.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.omc import is_reading_openvtb
from podiumd_tests.seed.openvtb import notifications_api_root

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.requires("omc", "openvtb", "cluster"),
    pytest.mark.source("Jira IN-3501", "Where OMC reads Open VTB, the settings the Berichtenbox chain needs are set."),
]


@pytest.fixture(name="berichtenbox_env")
def fixture_berichtenbox_env(podiumd_env: Environment) -> Environment:
    """The environment, where OMC reads Open VTB; skip elsewhere."""
    if not is_reading_openvtb(podiumd_env):
        pytest.skip("OMC's ZGW_ENDPOINT_OPENVTB is not set: the Berichtenbox scenario is off")
    return podiumd_env


@pytest.mark.scenario("""
    Given OMC reads Open VTB's berichten for the Berichtenbox
    Then OMC knows where to fetch a bericht's bijlagen from
""")
def test_omc_fetches_bijlagen_from_the_documenten_api(berichtenbox_env: Environment) -> None:
    """OMC's ZGW_ENDPOINT_DOCUMENTEN is set; without it every bericht goes out without its PDF."""
    endpoint = berichtenbox_env.variable("omc", "ZGW_ENDPOINT_DOCUMENTEN")
    assert endpoint, (
        "OMC's ZGW_ENDPOINT_DOCUMENTEN is empty: set omc.settings.zgw.endpoint.documenten to Open Zaak's Documenten API"
    )


@pytest.mark.scenario("""
    Given OMC reads Open VTB's berichten for the Berichtenbox
    Then Open VTB publishes its events to Open Notificaties under its own source
""")
def test_open_vtb_publishes_to_open_notificaties(berichtenbox_env: Environment) -> None:
    """Open VTB has an Open Notificaties service and NOTIFICATIONS_SOURCE; without either it sends no event."""
    problems = []
    if not notifications_api_root(berichtenbox_env):
        problems.append("Open VTB has no Open Notificaties service (setup_configuration notifications_config)")
    if not berichtenbox_env.variable("openvtb", "NOTIFICATIONS_SOURCE"):
        problems.append("Open VTB's NOTIFICATIONS_SOURCE is empty (openvtb.extraEnvVars)")
    assert not problems, "; ".join(problems)
