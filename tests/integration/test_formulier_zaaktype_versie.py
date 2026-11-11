"""Chain: after a new version of a zaaktype is published, Open Formulieren registers zaken on that version.

Open Formulieren caches its zaaktype lookup per catalogus, identificatie and date for an hour
(CATALOGI_CASE_TYPE_LOOKUP_CACHE_TIMEOUT in openforms.contrib.zgw.clients.catalogi).
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import cast

import pytest

from podiumd_tests.bootstrap.steps import NAW
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import submit
from podiumd_tests.seed.catalogi import make_publishable_zaaktype
from podiumd_tests.seed.catalogi import publish
from podiumd_tests.seed.openzaak import CATALOGI

if TYPE_CHECKING:
    from collections.abc import Callable

    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.openzaak import ZaaktypeParts
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires("openformulieren", "openzaak", "cluster"),
]

TIMEOUT = 90


def _version(  # one zaaktype version
    env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    template: JsonObject,
    parts: ZaaktypeParts,
    **fields: object,
) -> JsonObject:
    """Publish a version of a throwaway zaaktype that allows the test informatieobjecttype."""
    zaaktype = make_publishable_zaaktype(env, openzaak, registry, template, **fields)
    ziot = {"zaaktype": zaaktype["url"], "informatieobjecttype": parts.informatieobjecttype, "volgnummer": 1}
    openzaak.post(f"{CATALOGI}/zaaktype-informatieobjecttypen", {**ziot, "richting": "inkomend"})
    return publish(openzaak, zaaktype)


@pytest.mark.source(
    "podiumd-tests",
    "Open Formulieren caches the zaaktype it registers on; a new zaaktype version must still be used at once.",
)
@pytest.mark.xfail(
    strict=True,
    reason="[open-formulieren-7] Open Formulieren 4.0.7 caches the zaaktype lookup for an hour and registers zaken "
    "on the old version after a new one is published; not yet reported upstream",
)
@pytest.mark.scenario("""
    Given a form that registers zaken of a zaaktype, and a zaak registered with it
    When a new version of the zaaktype is published, valid from today, and the old one ends yesterday
    And the form is submitted again
    Then the new zaak has the new version of the zaaktype
""")
def test_new_zaaktype_version_is_used_at_once(  # one chain
    http: requests.Session,
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    test_zaaktype: JsonObject,
    parts: ZaaktypeParts,
    need_bootstrap: Callable[..., None],
) -> None:
    """The second submission's zaak is of the version published after the first submission."""
    need_bootstrap("openformulieren-zgw-group", "openzaak-of-autorisatie")
    if not test_zaaktype.get("selectielijstProcestype"):
        pytest.skip("test zaaktype has no selectielijstProcestype (Selectielijst API was unreachable at bootstrap)")
    today = datetime.now(tz=UTC).date()
    oud = _version(podiumd_env, openzaak, registry, test_zaaktype, parts, beginGeldigheid="2026-01-01")
    slug = registry.tagged("versie")
    options = {
        **cast("dict[str, object]", ZGW_REGISTRATION["options"]),
        "case_type_identification": oud["identificatie"],
    }
    make_form(podiumd_env, registry, slug, NAW, {**ZGW_REGISTRATION, "options": options})
    eerste = registered_zaak(
        podiumd_env, openzaak, registry, submit(podiumd_env, http, registry, slug, NAW_DATA, timeout=TIMEOUT)
    )
    assert eerste["zaaktype"] == oud["url"]

    openzaak.patch(str(oud["url"]), {"eindeGeldigheid": (today - timedelta(days=1)).isoformat()})
    nieuw = _version(
        podiumd_env,
        openzaak,
        registry,
        test_zaaktype,
        parts,
        identificatie=oud["identificatie"],
        beginGeldigheid=today.isoformat(),
    )
    tweede = registered_zaak(
        podiumd_env, openzaak, registry, submit(podiumd_env, http, registry, slug, NAW_DATA, timeout=TIMEOUT)
    )
    assert tweede["zaaktype"] == nieuw["url"], f"registered on {tweede['zaaktype']}, the old version is {oud['url']}"
