"""ZAC's access rules (its OPA policies): a user without ZAC roles cannot read a zaak that the admin can read.

Every ZAC REST call asks ZAC's OPA sidecar for the user's rights; a call that succeeds shows that OPA allows.
This checks the other side: the KCC test user (klantcontactmedewerker, no ZAC roles) is refused.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.steps import KCC
from podiumd_tests.responses import describe
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import zac_session

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

pytestmark = [pytest.mark.component, pytest.mark.requires("zac", "openzaak", "keycloak")]


@pytest.mark.source(
    "podiumd-tests",
    "ZAC's OPA policies must refuse a user without ZAC roles; helm-charts #633 updates OPA.",
)
def test_user_without_zac_roles_cannot_read_a_zaak(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures
    zac: requests.Session,
    podiumd_env: Environment,
    urls: dict[str, str],
    zac_zaak: Callable[..., JsonObject],
    need_bootstrap: Callable[..., None],
) -> None:
    """The admin reads the zaak; the KCC user, logged in to ZAC as well, gets 403 for the same zaak."""
    zaak = zac_zaak()
    url = f"{urls['zac']}/rest/zaken/zaak/{zaak['uuid']}"
    expect_status(zac.get(url), HTTPStatus.OK)
    need_bootstrap(KCC.name)
    kcc = zac_session(podiumd_env, KCC.username, podiumd_env.credentials.get(KCC.store_key))
    refused = kcc.get(url, allow_redirects=False)
    assert refused.status_code == HTTPStatus.FORBIDDEN, describe(refused)
