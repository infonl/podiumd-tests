"""OMC's Open VTB scenario: a published bericht reaches the inwoner by digitale post, or OMC drops it.

Open VTB's CloudEvent goes straight to OMC's Events/Listen. OMC answers 202 also when it drops a bericht on
purpose, with "Dropped: <reason>".
"""

from __future__ import annotations

import uuid

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.omc import notify_mock_missing
from podiumd_tests.mailpit import own_address
from podiumd_tests.omc import EMAIL
from podiumd_tests.omc import OMC_READS_NEW_OPENVTB
from podiumd_tests.omc import bericht_event
from podiumd_tests.omc import expect_outcome
from podiumd_tests.omc import listen
from podiumd_tests.omc import make_inwoner
from podiumd_tests.omc import notify_request
from podiumd_tests.omc import setting_skip
from podiumd_tests.responses import UnexpectedStatusError
from podiumd_tests.seed.openvtb import make_bericht
from podiumd_tests.workloads import expect_defect

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("omc", "openvtb", "cluster"),
    pytest.mark.source(
        "upstream Worth-NL/NotifyNL-OMC omc-notify.gitbook.io",
        "Bericht ontvangen: OMC forwards a published Open VTB bericht to a citizen, by e-mail when not to MijnOverheid.",
    ),
]

PUBLISHED = "bericht-gepubliceerd"


@pytest.mark.scenario("""
    Given Open VTB registered a bericht that is not yet published
    When OMC gets Open VTB's event about it
    Then OMC answers that the event needs no action
""")
def test_registered_bericht_needs_no_action(http: requests.Session, podiumd_env: Environment) -> None:
    """bericht-geregistreerd: 202, no notification."""
    event = bericht_event("bericht-geregistreerd", str(uuid.uuid4()))
    expect_outcome(listen(http, podiumd_env, event), HTTPStatus.ACCEPTED, "does not require action")


@pytest.mark.scenario("""
    Given a published bericht in Open VTB whose ontvanger is no citizen
    When OMC gets Open VTB's event about it
    Then OMC drops the bericht
""")
def test_bericht_to_a_non_citizen_is_dropped(
    request: pytest.FixtureRequest,
    http: requests.Session,
    podiumd_env: Environment,
    openvtb_berichten: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """An ontvanger URN without a BSN: 202 "Dropped", no notification."""
    expect_defect(
        request,
        podiumd_env,
        "omc",
        lambda version: version < OMC_READS_NEW_OPENVTB,
        raises=UnexpectedStatusError,
        reason="[omc-5] OMC before 2.3.2 requires mijnOverheidBerichtenbox on an Open VTB 0.2.0 bericht, where it lives "
        "on the berichttype, and cannot read any bericht (206); fixed in OMC v.2.3.2",
    )
    bericht = make_bericht(podiumd_env, openvtb_berichten, registry, "urn:ptest:ontvanger:1")
    event = bericht_event(PUBLISHED, str(bericht["uuid"]))
    expect_outcome(listen(http, podiumd_env, event), HTTPStatus.ACCEPTED, "Dropped: recipient is not a citizen")


@pytest.mark.requires("openklant")
@pytest.mark.scenario("""
    Given an inwoner with an e-mail address in Open Klant
    And a published bericht in Open VTB to the inwoner's BSN, not for MijnOverheid's berichtenbox
    When OMC gets Open VTB's event about it
    Then OMC asks Notify to send the inwoner the digitale post e-mail
""")
def test_bericht_is_mailed_to_the_inwoner(
    http: requests.Session,
    podiumd_env: Environment,
    need_bootstrap: Callable[..., None],
    openvtb_berichten: ApiClient,
    openklant: ApiClient,
    registry: ResourceRegistry,
) -> None:
    """A bericht to a citizen with an e-mail address makes OMC send the digitale post e-mail."""
    need_bootstrap("infra-mock-server")
    reason = notify_mock_missing(podiumd_env)
    if not reason and not podiumd_env.variable("omc", "NOTIFY_TEMPLATEID_EMAIL_MESSAGEBOX"):
        reason = "OMC's NOTIFY_TEMPLATEID_EMAIL_MESSAGEBOX is empty"
    if reason:
        pytest.skip(reason)
    adres = own_address(registry)
    bsn = make_inwoner(openklant, registry, adres)
    bericht = make_bericht(podiumd_env, openvtb_berichten, registry, f"urn:nld:brp:bsn:{bsn}")
    reason = setting_skip(podiumd_env, "ZGW_WHITELIST_VTBMESSAGE_TYPES", str(bericht["berichtType"]), listed=True)
    if reason:
        pytest.skip(reason)
    event = bericht_event(PUBLISHED, str(bericht["uuid"]))
    expect_outcome(listen(http, podiumd_env, event), HTTPStatus.ACCEPTED, "Digitale post (email) notification sent")
    notify_request(podiumd_env, EMAIL, adres, "NOTIFY_TEMPLATEID_EMAIL_MESSAGEBOX")
