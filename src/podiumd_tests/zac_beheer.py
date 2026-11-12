"""ZAC's beheer of referentietabellen and mailtemplates."""

from __future__ import annotations

import secrets

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.json_data import entries
from podiumd_tests.responses import expect_status
from podiumd_tests.zac import read_zaakafhandelparameters
from podiumd_tests.zac import save_zaakafhandelparameters

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Sequence

    import requests

    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

REFERENTIETABELLEN = "/rest/referentietabellen"
MAILTEMPLATES = "/rest/beheer/mailtemplates"
# RestReferenceTableValue.REFERENCE_TABLE_VALUE_MAX_LENGTH.
VALUE_MAX_LENGTH = 1000


def referentietabel(http: requests.Session, zac_url: str, code: str) -> JsonObject:
    """ZAC's referentietabel with this code, with its values."""
    response = http.get(f"{zac_url}{REFERENTIETABELLEN}/code/{code}")
    return cast("JsonObject", expect_status(response, HTTPStatus.OK).json())


def referentietabel_values(tabel: JsonObject) -> list[str]:
    """Return the names of the referentietabel's values, in ZAC's order."""
    return [str(value["name"]) for value in entries(tabel.get("values"))]


def communicatiekanalen(http: requests.Session, zac_url: str) -> list[str]:
    """Return the communicatiekanalen ZAC offers when a zaak is edited: those of its referentietabel but E-formulier."""
    response = http.get(f"{zac_url}{REFERENTIETABELLEN}/communicatiekanaal/false")
    return [str(kanaal) for kanaal in expect_status(response, HTTPStatus.OK).json()]


def has_same_values(tabel: JsonObject, other: JsonObject) -> bool:
    """Whether the referentietabellen hold the same values; ZAC 5.9.1 reads them in no fixed order."""
    return sorted(referentietabel_values(tabel)) == sorted(referentietabel_values(other))


def create_referentietabel(
    http: requests.Session, zac_url: str, registry: ResourceRegistry, values: list[str]
) -> JsonObject:
    """Create a referentietabel with a run-tagged code and name and these values; cleanup deletes it."""
    code = registry.tagged(f"zac-{secrets.token_hex(3)}").upper()
    body = {"code": code, "name": code, "values": [{"name": value} for value in values]}
    response = http.post(zac_url + REFERENTIETABELLEN, json=body)
    created = cast("JsonObject", expect_status(response, HTTPStatus.OK).json())

    def delete() -> None:
        # A test may have deleted it: ZAC answers 404.
        expect_status(delete_referentietabel(http, zac_url, created), HTTPStatus.NO_CONTENT, HTTPStatus.NOT_FOUND)

    registry.add(f"ZAC referentietabel {code}", delete)
    return created


def update_referentietabel(
    http: requests.Session, zac_url: str, tabel: JsonObject, values: Sequence[Mapping[str, object]]
) -> requests.Response:
    """Save the referentietabel with these values (name, systemValue; id of an existing one); ZAC's answer."""
    body = {"name": tabel["name"], "code": tabel["code"], "values": values}
    return http.put(f"{zac_url}{REFERENTIETABELLEN}/{tabel['id']}", json=body)


def delete_referentietabel(http: requests.Session, zac_url: str, tabel: JsonObject) -> requests.Response:
    """Delete the referentietabel; ZAC's answer."""
    return http.delete(f"{zac_url}{REFERENTIETABELLEN}/{tabel['id']}")


def guard_referentietabel(http: requests.Session, zac_url: str, registry: ResourceRegistry, tabel: JsonObject) -> None:
    """At cleanup, save the referentietabel (as read, with its values) back when its values differ then.

    For a request ZAC should refuse on an estate's table: a regression must not leave the table changed.
    """

    def restore() -> None:
        current = referentietabel(http, zac_url, str(tabel["code"]))
        if has_same_values(current, tabel):
            return
        ids = {value["name"]: value["id"] for value in entries(current.get("values"))}
        before = entries(tabel.get("values"))
        values = [{**value, "id": ids.get(value["name"])} for value in before]
        expect_status(update_referentietabel(http, zac_url, tabel, values), HTTPStatus.OK)

    registry.add(f"ZAC referentietabel {tabel['code']} as before", restore)


# The field of zaakafhandelparameters with their own mailtemplates, one per mail.
KOPPELINGEN = "mailtemplateKoppelingen"


def create_mailtemplate(http: requests.Session, zac_url: str, registry: ResourceRegistry) -> JsonObject:
    """Create a mailtemplate for mail from a zaak with a run-tagged name, not ZAC's default; cleanup deletes it.

    ZAC mails with the first default mailtemplate of a mail: a default one could replace the estate's.
    """
    naam = registry.tagged(f"zac-{secrets.token_hex(3)}")
    body = {
        "mailTemplateNaam": naam,
        "onderwerp": "podiumd-tests {ZAAK_NUMMER}",
        "body": "<p>podiumd-tests</p>",
        "mail": "ZAAK_ALGEMEEN",
        "defaultMailtemplate": False,
    }
    response = http.post(zac_url + MAILTEMPLATES, json=body)
    created = cast("JsonObject", expect_status(response, HTTPStatus.CREATED).json())
    # ZAC answers 204 also when a test deleted it.
    registry.add(f"ZAC mailtemplate {naam}", lambda: delete_mailtemplate(http, zac_url, created))
    return created


def link_mailtemplate(
    http: requests.Session, zac_url: str, zaaktype_uuid: str, template: JsonObject, registry: ResourceRegistry
) -> None:
    """Link the mailtemplate in the zaaktype's zaakafhandelparameters, replacing their links; cleanup restores them."""
    parameters = read_zaakafhandelparameters(http, zac_url, zaaktype_uuid)

    def restore() -> None:
        current = read_zaakafhandelparameters(http, zac_url, zaaktype_uuid)
        save_zaakafhandelparameters(http, zac_url, {**current, KOPPELINGEN: parameters[KOPPELINGEN]})

    registry.add(f"mailtemplates of zaaktype {zaaktype_uuid}", restore)
    save_zaakafhandelparameters(http, zac_url, {**parameters, KOPPELINGEN: [{"mailtemplate": template}]})


def mailtemplate(http: requests.Session, zac_url: str, template: JsonObject) -> requests.Response:
    """ZAC's answer to a read of the mailtemplate."""
    return http.get(f"{zac_url}{MAILTEMPLATES}/{template['id']}")


def update_mailtemplate(http: requests.Session, zac_url: str, template: JsonObject, **fields: object) -> None:
    """Save the mailtemplate with these fields changed."""
    response = http.put(f"{zac_url}{MAILTEMPLATES}/{template['id']}", json={**template, **fields})
    expect_status(response, HTTPStatus.OK)


def delete_mailtemplate(http: requests.Session, zac_url: str, template: JsonObject) -> None:
    """Delete the mailtemplate."""
    expect_status(http.delete(f"{zac_url}{MAILTEMPLATES}/{template['id']}"), HTTPStatus.NO_CONTENT)
