"""Differences in ZAC's REST API between ZAC 5.9 and 5.12 that the suite bridges."""

from __future__ import annotations

import json
import re

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Mapping

    import requests


# From ZAC 5.12 one zaaktype configuration holds a CMMN or BPMN processDefinition, saved with
# PUT /rest/zaakafhandelparameters/{zaaktype uuid}; ZAC 5.9 saves CMMN ones with PUT /rest/zaakafhandelparameters and
# links BPMN processes in /rest/zaaktype-bpmn-configuration.
PROCESS_DEFINITIONS = "/rest/zaakafhandelparameters/process-definitions"
_process_definitions: dict[str, bool] = {}


def has_process_definitions(http: requests.Session, zac_url: str) -> bool:
    """Return whether ZAC configures zaaktypen with a processDefinition (ZAC 5.12 and later); asked once per URL."""
    if zac_url not in _process_definitions:
        _process_definitions[zac_url] = http.get(zac_url + PROCESS_DEFINITIONS).status_code == HTTPStatus.OK
    return _process_definitions[zac_url]


# ZAC 5.12 renamed boolean fields: can, has and should prefixes, and isX where a @JsonbProperty says so (Yasson
# names a Kotlin isX property x otherwise). The suite speaks ZAC 5.9's names; only boolean values are renamed.
_IS = (
    "actief afgehandeld afgeschermd behandelaarVrijgegeven besluitVerplicht besluittypeAanwezig bewerkenToegestaan"
    " brpInstellingenCorrect"
    " commercieleVestiging concept datumKenmerkVerplicht defaultMail enabled enabledForZaaktype enabledGlobally inUse"
    " informatieobjecttypeEmailAanwezig nuGeldig ondertekend ontbreektInOpenZaak opschortingMogelijk"
    " resultaattypeAanwezig rolOverigeAanwezig speciaal statustypeAanvullendeInformatieVereist"
    " statustypeAfgerondAanwezig statustypeAfgerondLaatsteVolgnummer statustypeHeropendAanwezig"
    " statustypeInBehandelingAanwezig statustypeIntakeAanwezig uploaded valide vergrendeld verlengingMogelijk"
    " vervaldatumBesluitVerplicht zaakOntvankelijk zaakafhandelParametersValide zaakspecifiekAutoriseerbaar"
)
_CAN = (
    "afbreken behandelen beheren bekijkenZaakdata brondatumZetten converteren creerenDocument heropenen inbox"
    " inboxProductaanvragenVerwijderen koppelen lezen ondertekenen ontgrendelen ontkoppeldeDocumentenVerwijderen"
    " ontkoppelen startenTaak startenZaak toekennen toevoegenBagObject toevoegenBetrokkeneBedrijf"
    " toevoegenBetrokkenePersoon toevoegenDocument toevoegenInitiatorBedrijf toevoegenInitiatorPersoon"
    " toevoegenNieuweVersie vergrendelen versturenEmail versturenOntvangstbevestiging verwijderen"
    " verwijderenBetrokkene verwijderenInitiator wijzigen wijzigenDoorlooptijd wijzigenLocatie zakenTaken"
    " zakenTakenExporteren zakenTakenVerdelen zoeken"
)
_SHOULD = "createDocumentFromMail includeTaken resolveVariableAsEmptyString takenVerlengen"


def _prefixed(prefix: str, names: str) -> dict[str, str]:
    words = names.split()
    return {name: f"{prefix}{name[0].upper()}{name[1:]}" for name in words}


NEW_NAMES: dict[str, str] = {
    **_prefixed("is", _IS),
    **_prefixed("can", _CAN),
    **_prefixed("should", _SHOULD),
    "active": "isActive",
    "brpKoppelen": "isBrpKoppelenEnabled",
    "dashboard": "isDashboardEnabled",
    "eerdereOpschorting": "hasEerdereOpschorting",
    "gekoppeldeZaakDocumenten": "shouldIncludeGekoppeldeZaakDocumenten",
    "heeftOntvangstbevestigingVerstuurd": "isOntvangstbevestigingVerstuurd",
    "heeftWaarschuwingen": "hasWaarschuwingen",
    "indicatieGebruiksrecht": "hasGebruiksrecht",
    "kvkKoppelen": "isKvkKoppelenEnabled",
    "mail": "isMailEnabled",
    "servicenorm": "hasServicenorm",
}
OLD_NAMES = {new: old for old, new in NEW_NAMES.items()}
# Names that keep their ZAC 5.9 spelling in what the suite sends: human task parameters' actief, and rights,
# which the suite only reads.
_SENT_AS_IS = frozenset(("actief", *_CAN.split()))
SENT_NAMES = {old: new for old, new in NEW_NAMES.items() if old not in _SENT_AS_IS}


# ZAC 5.12 names a user's id username (RestUser); the fields that hold a user, and the calls that answer users.
USER_FIELDS = frozenset(("behandelaar", "medewerker", "gelockedDoor", "ontkoppeldDoor", "filterOntkoppeldDoor"))
USER_CALLS = re.compile(
    r"/rest/identity/(users|groups/[^/]+/users|loggedInUser)$"
    r"|/rest/zaken/zaak/[^/]+/zaakspecifiek-geautoriseerde-medewerkers(/kandidaten)?$"
)


@dataclass(frozen=True)
class Renaming:
    """How to rename JSON for one direction: boolean names, and a user's id field (from, to)."""

    names: Mapping[str, str]
    user_id: tuple[str, str]

    def apply(self, data: object, *, is_user: bool = False) -> object:
        """Return data renamed at every depth; is_user: data is a user or a list of users."""
        if isinstance(data, list):
            return [self.apply(item, is_user=is_user) for item in cast("list[object]", data)]
        if not isinstance(data, dict):
            return data
        found = cast("dict[str, object]", data)
        renamed: dict[str, object] = {}
        for key, value in found.items():
            name = self.names.get(key, key) if isinstance(value, bool) else key
            if is_user and key == self.user_id[0]:
                name = self.user_id[1]
            renamed[name] = self.apply(value, is_user=key in USER_FIELDS)
        return renamed


SENT = Renaming(SENT_NAMES, ("id", "username"))
READ = Renaming(OLD_NAMES, ("username", "id"))


def bridge_names(http: requests.Session, zac_url: str) -> None:
    """Make the session send and read ZAC 5.9's field names when ZAC is 5.12 or later."""
    send = cast("Callable[..., requests.Response]", http.send)

    def bridged(request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        url = str(request.url)
        if (
            not url.startswith(zac_url)
            or url.endswith(PROCESS_DEFINITIONS)
            or not has_process_definitions(http, zac_url)
        ):
            return send(request, **kwargs)
        if request.body and "json" in str(request.headers.get("Content-Type", "")):
            body = SENT.apply(json.loads(request.body))
            cast("Callable[..., None]", request.prepare_body)(None, None, body)
        response = send(request, **kwargs)
        if "json" in response.headers.get("Content-Type", "") and response.content:
            # requests keeps a read body in _content; .json() and .text read it from there.
            path = urlsplit(url).path
            body = READ.apply(response.json(), is_user=bool(USER_CALLS.search(path)))
            setattr(response, "_content", json.dumps(body).encode())  # noqa: B010
        return response

    http.send = bridged
