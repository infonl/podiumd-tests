"""ZAC's handling of productaanvragen: the zaak it starts, its contactgegevens and the Inbox productaanvragen."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.json_data import section
from podiumd_tests.openformulieren import complete_submission
from podiumd_tests.openformulieren import logged_in_submission
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import productaanvraag_registration
from podiumd_tests.responses import expect_status
from podiumd_tests.seed.objecten import forget_productaanvraag
from podiumd_tests.seed.openzaak import delete_zaak
from podiumd_tests.seed.zac_zaaktype import make_zac_zaaktype
from podiumd_tests.seed.zac_zaaktype import zac_as_admin
from podiumd_tests.wait import wait_until
from podiumd_tests.zac import PRODUCTAANVRAAG_TIMEOUT
from podiumd_tests.zac import list_page
from podiumd_tests.zac import read_zaak
from podiumd_tests.zac import recent_zaken
from podiumd_tests.zac import save_zaakafhandelparameters

if TYPE_CHECKING:
    import requests

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.catalogi import ZaaktypeTypes
    from podiumd_tests.seed.registry import ResourceRegistry


def productaanvraag_zaken(openzaak: ApiClient, kenmerk: str) -> list[JsonObject]:
    """Return the zaken started since yesterday with the productaanvraag's kenmerk in the toelichting."""
    # ZAC quotes it ("met kenmerk '<kenmerk>'"), so a kenmerk that is a prefix of another one does not match it.
    quoted = f"'{kenmerk}'"  # noqa: B907  # ZAC's quotes, not Python's repr
    return [zaak for zaak in recent_zaken(openzaak) if quoted in str(zaak.get("toelichting") or "")]


def productaanvraag_zaak(
    openzaak: ApiClient, registry: ResourceRegistry, kenmerk: str, timeout: float = PRODUCTAANVRAAG_TIMEOUT
) -> JsonObject:
    """Return the zaak ZAC starts for a productaanvraag, with its kenmerk in the toelichting; cleanup deletes it.

    openzaak: a client that may read and delete zaken of the zaaktype (bootstrap openzaak-client-productaanvraag).
    """

    def started() -> JsonObject | None:
        return next(iter(productaanvraag_zaken(openzaak, kenmerk)), None)

    def delete() -> None:
        zaak = started()
        if zaak:
            delete_zaak(openzaak, str(zaak["url"]), with_documents=True)

    # Registered before the wait, so a zaak started after a timeout goes too.
    registry.add(f"zaak for productaanvraag {kenmerk}", delete)
    return wait_until(started, timeout=timeout, interval=3, description=f"zaak for productaanvraag {kenmerk}")


def zaak_with_contactgegevens(zac: requests.Session, zac_url: str, uuid: str) -> JsonObject:
    """Return the zaak as ZAC shows it, once ZAC has linked the aanvraag's contactgegevens to it.

    ZAC links them after it assigned the zaak and added the betrokkenen, right before it sends the
    ontvangstbevestiging.
    """

    def shown() -> JsonObject | None:
        found = read_zaak(zac, zac_url, uuid)
        return found if found.get("zaakSpecificContactDetails") else None

    return wait_until(shown, timeout=PRODUCTAANVRAAG_TIMEOUT, description=f"contactgegevens on zaak {uuid}")


def inbox_productaanvragen(http: requests.Session, zac_url: str, productaanvraagtype: str) -> list[JsonObject]:
    """Return the entries of ZAC's Inbox productaanvragen of the productaanvraagtype."""
    return entries(inbox_productaanvragen_page(http, zac_url, productaanvraagtype, 0, 100).get("resultaten"))


def inbox_productaanvragen_page(
    http: requests.Session, zac_url: str, productaanvraagtype: str, page: int, max_results: int
) -> JsonObject:
    """Return one page of ZAC's Inbox productaanvragen of the productaanvraagtype, with its totaal."""
    return list_page(http, f"{zac_url}/rest/inbox-productaanvragen", {"type": productaanvraagtype}, page, max_results)


def inbox_productaanvraag(http: requests.Session, zac_url: str, productaanvraagtype: str) -> JsonObject:
    """Return the first entry of ZAC's Inbox productaanvragen of the productaanvraagtype, once ZAC lists one."""
    return wait_until(
        lambda: next(iter(inbox_productaanvragen(http, zac_url, productaanvraagtype)), None),
        timeout=PRODUCTAANVRAAG_TIMEOUT,
        description=f"productaanvraag {productaanvraagtype} in the Inbox productaanvragen",
    )


def clean_up_inbox_entries(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, productaanvraagtype: str
) -> None:
    """Delete, at cleanup, the entries of ZAC's Inbox productaanvragen of the productaanvraagtype."""

    def delete() -> None:
        for entry in inbox_productaanvragen(http, zac_url, productaanvraagtype):
            expect_status(http.delete(f"{zac_url}/rest/inbox-productaanvragen/{entry['id']}"), HTTPStatus.NO_CONTENT)

    registry.add(f"Inbox productaanvragen of type {productaanvraagtype}", delete)


def productaanvraag_zaaktype(  # noqa: PLR0913  # the zaaktype's parts
    env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    template: JsonObject,
    *,
    aanvraagtype: str,
    types: ZaaktypeTypes,
) -> requests.Session:
    """Configure a throwaway zaaktype in ZAC for productaanvragen of aanvraagtype; a ZAC admin session that may use it.

    The BRP koppeling is on: without it ZAC adds no initiator from the productaanvraag.
    """
    parameters = make_zac_zaaktype(env, openzaak, registry, template, types=types)
    # A login after make_zac_zaaktype: ZAC reads the rights on the zaaktype at login.
    zac = zac_as_admin(env)
    koppelingen = {"brpKoppelen": True, "kvkKoppelen": True}
    changed = {"productaanvraagtype": aanvraagtype, "betrokkeneKoppelingen": koppelingen}
    save_zaakafhandelparameters(zac, env.profile.urls["zac"], {**parameters, **changed})
    return zac


def submit_digid_aanvraag(  # noqa: PLR0913  # the form's parts
    env: Environment,
    objecten: ApiClient,
    registry: ResourceRegistry,
    *,
    objecttype: str,
    aanvraagtype: str,
    bsn: str,
) -> JsonObject:
    """Submit a new DigiD form as an inwoner with this BSN; the data of the productaanvraag it registered in Objecten.

    The form registers the logged-in BSN as initiator (productaanvraag_registration). Cleanup deletes form and object.
    """
    slug = registry.tagged("digid-aanvraag")
    registration = productaanvraag_registration(env, objecttype, aanvraagtype, auth_initiator=True)
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving", "showInSummary": True}
    make_form(env, registry, slug, [field], registration, ("digid_oidc",))
    http, submission, headers = logged_in_submission(env, registry, slug, "digid_oidc", {"bsn": [bsn]})
    data = {"omschrijving": slug}
    status = complete_submission(env, http, submission, headers, data, timeout=PRODUCTAANVRAAG_TIMEOUT)
    kenmerk = str(status["publicReference"])
    forget_productaanvraag(objecten, registry, kenmerk)
    found = objecten.list("objects", {"data_attr": f"bron__kenmerk__exact__{kenmerk}"})
    if len(found) != 1:
        msg = f"{len(found)} productaanvraag objects with kenmerk {kenmerk}"
        raise AssertionError(msg)
    return section(section(found[0], "record"), "data")
