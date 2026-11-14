"""The perf tier's ZAC calls, as ZAC's scripts/test-data/create-load.py loads it: a new zaak, an upload, a search."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_STORE_KEY
from podiumd_tests.bootstrap.steps import ADMIN
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.perf.runs import SEARCH_TERM
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import clean_up_zaak
from podiumd_tests.zac import create_zaak
from podiumd_tests.zac import productaanvraag_parameters
from podiumd_tests.zac import zac_session
from podiumd_tests.zac_documents import uploaded_document

if TYPE_CHECKING:
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.perf.zgw_calls import Call
    from podiumd_tests.perf.zgw_calls import Prepared
    from podiumd_tests.seed.registry import ResourceRegistry


def zac_calls(env: Environment) -> dict[str, Call | Prepared]:
    """Return ZAC's calls, as the test admin; each new zaak is deleted after its timing."""
    zac_url = env.profile.urls["zac"]
    zac = zac_session(env, ADMIN.username, env.credentials.get(ADMIN.store_key))
    openzaak = openzaak_client(env, ZGW_PRODUCTAANVRAAG_CLIENT_ID, ZGW_PRODUCTAANVRAAG_STORE_KEY, "perf")
    parameters = productaanvraag_parameters(zac, zac_url, env.profile)

    def new_zaak(registry: ResourceRegistry) -> JsonObject:
        zaak = create_zaak(zac, zac_url, parameters, omschrijving=registry.tagged("perf-zaak"))
        clean_up_zaak(zac, zac_url, openzaak, registry, zaak)
        return zaak

    query = {"page": 0, "rows": 10, "type": "ZAAK", "zoeken": {"ALLE": SEARCH_TERM}}
    return {
        "zac_zaak_create": new_zaak,
        # The zaak's cleanup deletes the document.
        "zac_document_upload": (
            lambda registry: (new_zaak(registry), registry),
            lambda prepared: uploaded_document(zac, zac_url, *cast("tuple[JsonObject, ResourceRegistry]", prepared)),
        ),
        "zac_search": lambda _registry: expect_status(zac.put(f"{zac_url}/rest/zoeken/list", json=query), 200),
    }
