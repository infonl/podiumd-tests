"""The perf tier's portal calls: a logged-in inwoner's Mijn zaken and a zaak's status, as htmx loads them.

Open Inwoner's performance-tests (maykinmedia/open-inwoner). The suite's API group has no zaken cache
(wiring W4), so every call fetches the zaken from Open Zaak, as the source's uncached calls do.
"""

from __future__ import annotations

from itertools import cycle
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap.steps import DIGID_IDENTITIES
from podiumd_tests.openinwoner import HTMX
from podiumd_tests.openinwoner import MIJN_ZAKEN
from podiumd_tests.openinwoner import portal_session
from podiumd_tests.openinwoner import portal_zaak
from podiumd_tests.openinwoner import zaak_status_url
from podiumd_tests.perf.runs import PORTAL_CALLS
from podiumd_tests.perf.zgw_calls import suite_openzaak
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.openzaak import zaaktype_parts

if TYPE_CHECKING:
    from collections.abc import Collection

    import requests

    from podiumd_tests.environment import Environment
    from podiumd_tests.perf.zgw_calls import Call
    from podiumd_tests.seed.registry import ResourceRegistry

# The Locust users of a process take turns with the DigiD identities.
_IDENTITIES = cycle(DIGID_IDENTITIES)


def portal_calls(env: Environment, registry: ResourceRegistry, selected: Collection[str]) -> dict[str, Call]:
    """Return the next DigiD identity's Mijn zaken list and its new zaak's status; the registry gets the zaak.

    Empty, without a login or zaak, when the environment has no portal or none of PORTAL_CALLS is selected.
    """
    if "openinwoner" not in env.profile.urls or not set(PORTAL_CALLS).intersection(selected):
        return {}
    identity = next(_IDENTITIES)
    openzaak, zaaktype = suite_openzaak(env)
    zaak = portal_zaak(openzaak, registry, zaaktype_parts(openzaak, zaaktype), identity)
    portal = portal_session(env, "digid", identity)
    list_url = f"{env.profile.urls['openinwoner']}{MIJN_ZAKEN}content/"

    def fragment(url: str) -> requests.Response:
        return expect_status(portal.get(url, headers=HTMX), 200)

    status_url = f"{zaak_status_url(fragment(list_url).text, list_url, zaak)}content/"
    return {
        "oi_mijn_zaken": lambda _registry: fragment(list_url),
        "oi_zaak_status": lambda _registry: fragment(status_url),
    }
