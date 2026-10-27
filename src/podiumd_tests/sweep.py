"""Find and delete what test runs left behind: objects carrying a run tag older than a cutoff.

Tests clean up after themselves; this catches what an interrupted run or a failed cleanup
left. Bootstrap objects (ptest-bootstrap-*) are never touched. Finders run in
order: objects that refer to others go first.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from typing import TYPE_CHECKING

from podiumd_tests.bootstrap import check
from podiumd_tests.bootstrap.names import TEST_CATALOGUS_RSIN
from podiumd_tests.bootstrap.names import ZGW_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_CLIENT_ID
from podiumd_tests.bootstrap.names import ZGW_PRODUCTAANVRAAG_STORE_KEY
from podiumd_tests.bootstrap.names import ZGW_STORE_KEY
from podiumd_tests.bootstrap.steps import STEPS
from podiumd_tests.clients.platform import mailpit_client
from podiumd_tests.clients.platform import objecten_client
from podiumd_tests.clients.platform import openklant_client
from podiumd_tests.clients.platform import opennotificaties_client
from podiumd_tests.clients.platform import openzaak_client
from podiumd_tests.json_data import entries
from podiumd_tests.mailpit import delete_message
from podiumd_tests.openformulieren import remove_form
from podiumd_tests.openformulieren import tagged_forms
from podiumd_tests.results import RUN_TAG
from podiumd_tests.results import run_started
from podiumd_tests.seed.opennotificaties import delete_abonnement
from podiumd_tests.seed.openzaak import BESLUITEN
from podiumd_tests.seed.openzaak import CATALOGI
from podiumd_tests.seed.openzaak import DOCUMENTEN
from podiumd_tests.seed.openzaak import ZAKEN
from podiumd_tests.seed.openzaak import delete_zaak

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject

# The audit trail names sweep as the actor of its deletions.
SWEEP_TAG = "podiumd-tests-sweep"


def format_swept(swept: list[Swept]) -> str:
    """One line per leftover or skipped kind, for the terminal."""
    lines = [f"{s.action:<8} {s.kind:<20} {s.name} {s.detail}".rstrip() for s in swept]
    return "\n".join(lines) or "nothing to sweep"


def is_stale(item: object, cutoff: datetime) -> bool:
    """The item carries a run tag of a run that started before cutoff (a legacy tag always counts)."""
    for tag in RUN_TAG.findall(json.dumps(item)):
        started = run_started(tag)
        if started is None or started < cutoff:
            return True
    return False


def _delete(client: ApiClient) -> Callable[[JsonObject], None]:
    return lambda item: client.delete(str(item["url"]))


@dataclass(frozen=True)
class Finder:  # pylint: disable=too-many-instance-attributes  # a record of one kind
    """One kind of leftover: where to list it and how to delete one."""

    kind: str
    component: str
    step: str
    client: Callable[[Environment], ApiClient]
    path: str
    params: dict[str, str]
    delete: Callable[[ApiClient], Callable[[JsonObject], None]] = _delete
    # Adds what tells whether an item is stale, from outside the item.
    with_context: Callable[[Environment, ApiClient, list[JsonObject]], list[JsonObject]] | None = None

    def items(self, env: Environment, client: ApiClient) -> list[JsonObject]:
        """Everything the list returns; Mailpit's search answers with "messages"."""
        if self.component == "mailpit":
            return entries(client.get(self.path, self.params).get("messages"))
        found = client.list(self.path, self.params)
        return self.with_context(env, client, found) if self.with_context else found


def _openzaak(env: Environment) -> ApiClient:
    return openzaak_client(env, ZGW_CLIENT_ID, ZGW_STORE_KEY, SWEEP_TAG)


def _openzaak_productaanvraag(env: Environment) -> ApiClient:
    return openzaak_client(env, ZGW_PRODUCTAANVRAAG_CLIENT_ID, ZGW_PRODUCTAANVRAAG_STORE_KEY, SWEEP_TAG)


def with_productaanvraag(env: Environment, openzaak: ApiClient, zaken: list[JsonObject]) -> list[JsonObject]:
    """The zaken, each started for a run-tagged productaanvraag with that object under "productaanvraag".

    The kenmerk of a productaanvraag that Open Formulieren registers is its public reference, without a run tag.
    """
    by_url = {str(z["url"]): z for z in zaken}
    for item in objecten_client(env).list("objects", {}):
        if not RUN_TAG.search(json.dumps(item)):
            continue
        for link in openzaak.list(f"{ZAKEN}/zaakobjecten", {"object": str(item["url"])}):
            zaak = str(link["zaak"])
            if zaak in by_url:
                by_url[zaak] = {**by_url[zaak], "productaanvraag": item}
    return list(by_url.values())


def _zaak(client: ApiClient) -> Callable[[JsonObject], None]:
    return lambda item: delete_zaak(client, str(item["url"]))


def _abonnement(client: ApiClient) -> Callable[[JsonObject], None]:
    return lambda item: delete_abonnement(client, str(item["url"]))


def _message(client: ApiClient) -> Callable[[JsonObject], None]:
    return lambda item: delete_message(client, str(item["ID"]))


RSIN = {"bronorganisatie": TEST_CATALOGUS_RSIN}
FINDERS: tuple[Finder, ...] = (
    Finder(
        "besluit",
        "openzaak",
        "openzaak-client",
        _openzaak,
        f"{BESLUITEN}/besluiten",
        {"verantwoordelijkeOrganisatie": TEST_CATALOGUS_RSIN},
    ),
    Finder("zaak", "openzaak", "openzaak-client", _openzaak, f"{ZAKEN}/zaken", RSIN, _zaak),
    Finder(
        "productaanvraag zaak",
        "zac",
        "openzaak-client-productaanvraag",
        _openzaak_productaanvraag,
        f"{ZAKEN}/zaken",
        {},
        _zaak,
        with_productaanvraag,
    ),
    Finder("document", "openzaak", "openzaak-client", _openzaak, f"{DOCUMENTEN}/enkelvoudiginformatieobjecten", RSIN),
    Finder(
        "concept zaaktype", "openzaak", "openzaak-client", _openzaak, f"{CATALOGI}/zaaktypen", {"status": "concept"}
    ),
    Finder("internetaak", "openklant", "openklant-token", openklant_client, "internetaken", {}),
    Finder("klantcontact", "openklant", "openklant-token", openklant_client, "klantcontacten", {}),
    Finder("digitaal adres", "openklant", "openklant-token", openklant_client, "digitaleadressen", {}),
    Finder("partij", "openklant", "openklant-token", openklant_client, "partijen", {}),
    Finder("actor", "openklant", "openklant-token", openklant_client, "actoren", {}),
    Finder(
        "abonnement",
        "opennotificaties",
        "opennotificaties-client",
        opennotificaties_client,
        "abonnement",
        {},
        _abonnement,
    ),
    Finder("object", "objecten", "objecten-token", objecten_client, "objects", {}),
    Finder("mail", "mailpit", "", mailpit_client, "search", {"query": 'subject:"ptest-"'}, _message),
    Finder("mail", "mailpit", "", mailpit_client, "search", {"query": 'to:"ptest-"'}, _message),
)


@dataclass(frozen=True)
class Swept:
    """One leftover, or one kind that could not be searched."""

    kind: str
    name: str
    action: str  # "deleted", "found" (dry run), "failed" or "skipped"
    detail: str = ""


def _name(item: JsonObject) -> str:
    return str(item.get("url") or item.get("slug") or item.get("Subject") or item.get("ID") or "?")


def _sweep_items(
    kind: str, items: list[JsonObject], delete: Callable[[JsonObject], None], cutoff: datetime, *, dry_run: bool
) -> list[Swept]:
    swept: list[Swept] = []
    for item in items:
        if not is_stale(item, cutoff):
            continue
        if dry_run:
            swept.append(Swept(kind, _name(item), "found"))
            continue
        try:
            delete(item)
        except (AssertionError, OSError, ValueError) as exc:
            swept.append(Swept(kind, _name(item), "failed", f"{type(exc).__name__}: {exc}"))
        else:
            swept.append(Swept(kind, _name(item), "deleted"))
    return swept


def sweep(env: Environment, cutoff: datetime, *, dry_run: bool) -> list[Swept]:
    """Delete (or with dry_run, list) the stale run-tagged objects of every finder, then the test forms."""
    present = {o.step for o in check(env, STEPS) if o.action == "present"}
    swept: list[Swept] = []
    for finder in FINDERS:
        reason = env.capabilities.skip_reason(finder.component)
        if reason is None and finder.step and finder.step not in present:
            reason = f"bootstrap step {finder.step} missing"
        if reason:
            swept.append(Swept(finder.kind, "", "skipped", reason))
            continue
        client = finder.client(env)
        swept += _sweep_items(finder.kind, finder.items(env, client), finder.delete(client), cutoff, dry_run=dry_run)
    reason = env.capabilities.skip_reason("openformulieren", "cluster")
    if reason:
        return [*swept, Swept("form", "", "skipped", reason)]
    forms: list[JsonObject] = [{"slug": slug} for slug in tagged_forms(env)]
    return swept + _sweep_items(
        "form", forms, lambda item: remove_form(env, str(item["slug"])), cutoff, dry_run=dry_run
    )
