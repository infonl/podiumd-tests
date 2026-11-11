"""Bootstrap step in Open Zaak: a published test zaaktype in the test catalogus, with what the tests use.

An informatieobjecttype, statustypen (the last is the eindstatus), initiator, behandelaar
and belanghebbende roltypen, eigenschap "kenteken", a published besluittype, and a
resultaattype whose selectielijst klasse comes from Open Zaak's own Selectielijst API (left out,
with a note, when that API cannot be reached).
Actions: status, apply (recreates; adds missing statustypen in place, keeping the zaaktype's uuid and zaken), remove
(also the zaken of the zaaktype and the documents of its type).
Params: action, domein, rsin, identificatie, iot_omschrijving, besluittype; optional statustypen (default
STATUSTYPEN, the last is the eindstatus); optional versions, a list of
[begin, end] dates (ISO, end may be null): one published version each, whose statustypen end in " v<n>";
optional archief: one resultaattype per afleidingswijze of ARCHIEF, named after it, eigenschap "peildatum"
and the zaaktype as its own deelzaaktype, for the archiefactiedatum tests.
"""

STATUSTYPEN = ("Ingediend", "In behandeling", "Afgehandeld")
ROLTYPEN = (("Initiator", "initiator"), ("Behandelaar", "behandelaar"), ("Belanghebbende", "belanghebbende"))
# Brondatum afleidingswijzen whose date the tests can set; zaakobject, termijn and gerelateerde_zaak are not covered.
ARCHIEF = (
    "afgehandeld",
    "hoofdzaak",
    "eigenschap",
    "ingangsdatum_besluit",
    "vervaldatum_besluit",
    "ander_datumkenmerk",
)
PEILDATUM = "peildatum"


def run(params):
    import datetime as dt

    from django.db import transaction
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import Catalogus
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.catalogi.models import ZaakType
    from openzaak.components.documenten.models import EnkelvoudigInformatieObject
    from openzaak.components.zaken.models import Zaak

    catalogus = Catalogus.objects.filter(domein=params["domein"], rsin=params["rsin"]).first()
    zaaktypen = ZaakType.objects.filter(catalogus=catalogus, identificatie=params["identificatie"])
    iots = InformatieObjectType.objects.filter(catalogus=catalogus, omschrijving=params["iot_omschrijving"])
    besluittypen = BesluitType.objects.filter(catalogus=catalogus, omschrijving=params["besluittype"])

    today = dt.datetime.now(tz=dt.UTC).date()
    versions = [
        (dt.date.fromisoformat(begin), end and dt.date.fromisoformat(end), f" v{number}")
        for number, (begin, end) in enumerate(params.get("versions") or [], start=1)
    ] or [(today, None, "")]
    statustypen = _statustypen_per_version(params, zaaktypen, versions)
    complete = catalogus and statustypen is not None and iots.exists() and besluittypen.exists()
    if params["action"] == "status":
        return {"present": bool(complete and all(has == wanted for _, has, wanted in statustypen))}
    if params["action"] == "apply" and complete and _added_in_place(statustypen):
        return {"present": True}
    # zaaktype is a "foreign key or URL" field; _zaaktype is its local foreign key.
    Zaak.objects.filter(_zaaktype__in=zaaktypen).delete()
    # Documents protect their informatieobjecttype; one per canonical deletes all its versions.
    documents = EnkelvoudigInformatieObject.objects.filter(_informatieobjecttype__in=iots)
    canonicals = {document.canonical for document in documents}
    for canonical in canonicals:
        canonical.delete()
    zaaktypen.delete()
    iots.delete()
    besluittypen.delete()
    if params["action"] == "remove":
        return {"present": False}

    with transaction.atomic():  # all or nothing: a failure leaves no half zaaktype
        return _create(params, catalogus, versions)


def _create(params, catalogus, versions):
    import datetime as dt

    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import InformatieObjectType

    iot = InformatieObjectType.objects.create(
        catalogus=catalogus,
        omschrijving=params["iot_omschrijving"],
        informatieobjectcategorie="podiumd-tests",
        vertrouwelijkheidaanduiding="openbaar",
        datum_begin_geldigheid=min(begin for begin, _, _ in versions),
        concept=False,
    )
    besluittype = BesluitType.objects.create(
        catalogus=catalogus,
        omschrijving=params["besluittype"],
        besluitcategorie="podiumd-tests",
        reactietermijn=dt.timedelta(days=14),
        publicatie_indicatie=False,
        datum_begin_geldigheid=min(begin for begin, _, _ in versions),
        concept=False,
    )
    notes = []
    for begin, end, suffix in versions:
        zaaktype = _version(params, catalogus, iot, begin, end, suffix)
        besluittype.zaaktypen.add(zaaktype)
        if params.get("archief"):
            _archief(zaaktype)
        notes += _resultaattypen(zaaktype, ARCHIEF if params.get("archief") else ("afgehandeld",))
    return {"present": True, "notes": sorted(set(notes))}


def _version(params, catalogus, iot, begin, end, suffix):  # noqa: PLR0913, PLR0917  # one version
    import datetime as dt

    from openzaak.components.catalogi.models import Eigenschap
    from openzaak.components.catalogi.models import EigenschapSpecificatie
    from openzaak.components.catalogi.models import RolType
    from openzaak.components.catalogi.models import ZaakType
    from openzaak.components.catalogi.models import ZaakTypeInformatieObjectType

    zaaktype = ZaakType.objects.create(
        catalogus=catalogus,
        identificatie=params["identificatie"],
        zaaktype_omschrijving=params["identificatie"],
        vertrouwelijkheidaanduiding="openbaar",
        doel="podiumd-tests",
        aanleiding="podiumd-tests",
        indicatie_intern_of_extern="extern",
        handeling_initiator="Indienen",
        onderwerp="Klacht",
        handeling_behandelaar="Behandelen",
        doorlooptijd_behandeling=dt.timedelta(days=30),
        opschorting_en_aanhouding_mogelijk=False,
        verlenging_mogelijk=False,
        publicatie_indicatie=False,
        verantwoordingsrelatie=[],
        producten_of_diensten=[],
        referentieproces_naam="podiumd-tests",
        datum_begin_geldigheid=begin,
        datum_einde_geldigheid=end,
        versiedatum=begin,
        concept=False,
    )
    ZaakTypeInformatieObjectType.objects.create(
        zaaktype=zaaktype, informatieobjecttype=iot, volgnummer=1, richting="inkomend"
    )
    _number_statustypen(zaaktype, [name + suffix for name in params.get("statustypen") or STATUSTYPEN])
    for omschrijving, generiek in ROLTYPEN:
        RolType.objects.create(zaaktype=zaaktype, omschrijving=omschrijving, omschrijving_generiek=generiek)
    specificatie = EigenschapSpecificatie.objects.create(formaat="tekst", lengte="20", kardinaliteit="1")
    Eigenschap.objects.create(
        zaaktype=zaaktype, eigenschapnaam="kenteken", definitie="Kenteken", specificatie_van_eigenschap=specificatie
    )
    return zaaktype


def _statustypen_per_version(params, zaaktypen, versions):
    """Return (zaaktype, its statustypen, the wanted ones) per published version; None when a version is missing."""
    published = list(zaaktypen.filter(concept=False).order_by("datum_begin_geldigheid"))
    if len(published) != len(versions):
        return None
    names = params.get("statustypen") or STATUSTYPEN
    return [
        (zaaktype, list(_statustypen(zaaktype)), [name + suffix for name in names])
        for zaaktype, (_, _, suffix) in zip(published, versions, strict=True)
    ]


def _added_in_place(statustypen):
    """Add the missing statustypen to each version; False, changing nothing, when one has a statustype not wanted."""
    from django.db import transaction

    if not all(set(has) <= set(wanted) for _, has, wanted in statustypen):
        return False
    with transaction.atomic():
        for zaaktype, _, wanted in statustypen:
            _number_statustypen(zaaktype, wanted)
    return True


def _statustypen(zaaktype):
    """Return the zaaktype's statustypen by omschrijving, in volgnummer order."""
    from openzaak.components.catalogi.models import StatusType

    found = StatusType.objects.filter(zaaktype=zaaktype).order_by("statustypevolgnummer")
    return {statustype.statustype_omschrijving: statustype for statustype in found}


def _number_statustypen(zaaktype, wanted):
    """Give the zaaktype the statustypen of wanted, numbered in that order; create the missing ones."""
    from openzaak.components.catalogi.models import StatusType

    has = _statustypen(zaaktype)
    # Last first: a volgnummer is unique per zaaktype, and an added statustype only moves the later ones up.
    for number, name in reversed(list(enumerate(wanted, start=1))):
        # informeren: OMC mails the initiator on each status (TA seed-minimal).
        statustype = has.get(name) or StatusType(zaaktype=zaaktype, statustype_omschrijving=name, informeren=True)
        statustype.statustypevolgnummer = number
        statustype.save()


def _archief(zaaktype):
    """Add the date eigenschap of afleidingswijze eigenschap and make the zaaktype its own deelzaaktype."""
    from openzaak.components.catalogi.models import Eigenschap
    from openzaak.components.catalogi.models import EigenschapSpecificatie

    specificatie = EigenschapSpecificatie.objects.create(formaat="tekst", lengte="30", kardinaliteit="1")
    Eigenschap.objects.create(
        zaaktype=zaaktype, eigenschapnaam=PEILDATUM, definitie="Peildatum", specificatie_van_eigenschap=specificatie
    )
    zaaktype.deelzaaktypen.add(zaaktype)


def _resultaattypen(zaaktype, afleidingswijzen):
    """Create a resultaattype per afleidingswijze from the first 2020 selectielijst procestype; notes when not possible.

    One afleidingswijze is named Afgehandeld; several are named after their afleidingswijze.
    """
    import datetime as dt

    from openzaak.components.catalogi.models import ResultaatType
    from openzaak.selectielijst.models import ReferentieLijstConfig
    from zgw_consumers.client import build_client

    try:
        with build_client(ReferentieLijstConfig.get_solo().service) as client:
            proces = client.get("procestypen", params={"jaar": 2020}).json()[0]
            resultaat = client.get("resultaten", params={"procesType": proces["url"]}).json()["results"][0]
            omschrijving = client.get("resultaattypeomschrijvingen").json()[0]
    except Exception as exc:  # noqa: BLE001  # any failure: no resultaattype, but the rest stays usable
        return [f"no resultaattype: Selectielijst API unreachable ({type(exc).__name__})"]
    zaaktype.selectielijst_procestype = proces["url"]
    zaaktype.save()
    for afleidingswijze in afleidingswijzen:
        ResultaatType.objects.create(
            zaaktype=zaaktype,
            omschrijving="Afgehandeld" if len(afleidingswijzen) == 1 else afleidingswijze,
            resultaattypeomschrijving=omschrijving["url"],
            selectielijstklasse=resultaat["url"],
            archiefnominatie="vernietigen",
            archiefactietermijn=dt.timedelta(days=3650),
            brondatum_archiefprocedure_afleidingswijze=afleidingswijze,
            brondatum_archiefprocedure_datumkenmerk=PEILDATUM
            if afleidingswijze in {"eigenschap", "ander_datumkenmerk"}
            else "",
        )
    return []
