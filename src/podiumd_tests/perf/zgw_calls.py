"""The perf tier's calls to the ZGW components: Open Zaak and Open Notificaties."""

from __future__ import annotations

import secrets

from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.bootstrap.names import PERF_KANAAL
from podiumd_tests.bootstrap.names import TEST_ZAAKTYPE
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.json_data import strings
from podiumd_tests.seed.openklant import random_bsn
from podiumd_tests.seed.openzaak import BSN_FILTER
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import link_document
from podiumd_tests.seed.openzaak import make_document
from podiumd_tests.seed.openzaak import make_zaak
from podiumd_tests.seed.openzaak import published_zaaktype

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

# Open Zaak's performance_test reads documents and zaken at page 34 of 100.
PAGE_SIZE = 100
DEEP_PAGE = 34
type Call = Callable[[ResourceRegistry], object]
# A call whose setup is not timed: prepare(registry) makes what the timed part needs and gets its cleanup.
type Prepared = tuple[Callable[[ResourceRegistry], object], Callable[[object], object]]


def _deep_page(openzaak: ApiClient, path: str) -> str:
    """Return the page Open Zaak's own benchmark reads (34 of 100), or the last one when there are fewer."""
    count = int(str(openzaak.get(path, {"pageSize": str(PAGE_SIZE)})["count"]))
    return str(max(1, min(DEEP_PAGE, -(-count // PAGE_SIZE))))


def openzaak_calls(env: Environment) -> dict[str, Call | Prepared]:
    """Return Open Zaak's calls: zaken, documents and their links, by the suite's client and a limited one."""
    openzaak = openzaak_client(env, ZGW_CLIENT_ID, ZGW_STORE_KEY, "perf")
    test_zaaktype = published_zaaktype(openzaak, TEST_ZAAKTYPE, "openzaak-zaaktype")
    zaaktype = str(test_zaaktype["url"])
    iot = strings(test_zaaktype.get("informatieobjecttypen"))[0]
    documenten = f"{DOCUMENTEN}/enkelvoudiginformatieobjecten"
    ordered = {"pageSize": str(PAGE_SIZE), "ordering": "-auteur", "page": _deep_page(openzaak, documenten)}
    calls: dict[str, Call | Prepared] = {
        "oz_zaken": lambda _registry: openzaak.request("GET", f"{ZAKEN}/zaken", 200, params={"pageSize": "20"}),
        "oz_zaaktypen": lambda _registry: openzaak.request("GET", f"{CATALOGI}/zaaktypen", 200),
        "oz_zaak_create": lambda registry: make_zaak(openzaak, registry, zaaktype),
        # Mijn zaken: the zaken of one inwoner, a join over every zaak's rollen.
        "oz_zaken_by_bsn": lambda _registry: openzaak.request(
            "GET", f"{ZAKEN}/zaken", 200, params={BSN_FILTER: random_bsn()}
        ),
        "oz_documenten_ordered": lambda _registry: openzaak.request("GET", documenten, 200, params=ordered),
        # The document mix of Baseflow's DMF PoC: one document read, created, changed and linked.
        "oz_document_get": (
            lambda registry: make_document(openzaak, registry, iot),
            lambda document: openzaak.get(str(_url(document))),
        ),
        "oz_document_create": lambda registry: make_document(
            openzaak, registry, iot, bestandsnaam=f"{registry.tagged(secrets.token_hex(4))}.txt"
        ),
        "oz_document_patch": (
            lambda registry: make_document(openzaak, registry, iot),
            lambda document: _patch_document(openzaak, str(_url(document))),
        ),
        "oz_oio_list": (
            lambda registry: make_document(openzaak, registry, iot),
            lambda document: openzaak.request(
                "GET", f"{DOCUMENTEN}/objectinformatieobjecten", 200, params={"informatieobject": str(_url(document))}
            ),
        ),
        # In Open Zaak an objectinformatieobject comes with the zaakinformatieobject (drc-004): this times both.
        "oz_zio_create": (
            lambda registry: (
                registry,
                make_zaak(openzaak, registry, zaaktype),
                make_document(openzaak, registry, iot),
            ),
            lambda prepared: link_document(
                openzaak, *cast("tuple[ResourceRegistry, JsonObject, JsonObject]", prepared)
            ),
        ),
    }
    if "zac" in env.profile.urls:
        # A client with rights on one zaaktype, as every PodiumD app has: Open Zaak filters by its autorisaties.
        limited = openzaak_client(env, ZGW_PRODUCTAANVRAAG_CLIENT_ID, ZGW_PRODUCTAANVRAAG_STORE_KEY, "perf")
        page = {"pageSize": "20"}
        calls["oz_zaken_one_zaaktype"] = lambda _registry: limited.request("GET", f"{ZAKEN}/zaken", 200, params=page)
    return calls


def _url(created: object) -> object:
    return cast("JsonObject", created)["url"]


def _patch_document(openzaak: ApiClient, url: str) -> None:
    """Lock, PATCH the beschrijving and unlock a document, as ZAC changes one."""
    lock = openzaak.request("POST", f"{url}/lock", 200, json={}).json()["lock"]
    openzaak.request("PATCH", url, 200, json={"beschrijving": "perf", "lock": lock})
    openzaak.request("POST", f"{url}/unlock", 204, json={"lock": lock})


def opennotificaties_calls(env: Environment) -> dict[str, Call | Prepared]:
    """Open Notificaties' one call that matters: a notificatie, on a kanaal nothing subscribes to."""
    opennotificaties = opennotificaties_client(env)
    body: dict[str, object] = {
        "kanaal": PERF_KANAAL,
        "hoofdObject": f"{env.profile.urls['opennotificaties']}/perf",
        "resource": "perf",
        "resourceUrl": f"{env.profile.urls['opennotificaties']}/perf",
        "actie": "create",
        "kenmerken": {},
    }
    return {
        "onrc_notificatie": lambda _registry: opennotificaties.request(
            "POST", "notificaties", 200, 201, json={**body, "aanmaakdatum": datetime.now(tz=UTC).isoformat()}
        )
    }
