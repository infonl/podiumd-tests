"""Bootstrap step in Open Zaak: a published test zaaktype in the test catalogus, with what the tests use.

An informatieobjecttype, three statustypen (the last is the eindstatus), initiator, behandelaar
and belanghebbende roltypen, eigenschap "kenteken", a published besluittype, and a
resultaattype whose selectielijst klasse comes from Open Zaak's own Selectielijst API (left out,
with a note, when that API cannot be reached).
Actions: status, apply (recreates), remove (also the zaken of the zaaktype).
Params: action, domein, rsin, identificatie, iot_omschrijving, besluittype.
"""

STATUSTYPEN = ("Ingediend", "In behandeling", "Afgehandeld")
ROLTYPEN = (("Initiator", "initiator"), ("Behandelaar", "behandelaar"), ("Belanghebbende", "belanghebbende"))


def run(params):
    import datetime

    from django.db import transaction
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import Catalogus
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.catalogi.models import ZaakType
    from openzaak.components.zaken.models import Zaak

    catalogus = Catalogus.objects.filter(domein=params["domein"], rsin=params["rsin"]).first()
    zaaktypen = ZaakType.objects.filter(catalogus=catalogus, identificatie=params["identificatie"])
    iots = InformatieObjectType.objects.filter(catalogus=catalogus, omschrijving=params["iot_omschrijving"])
    besluittypen = BesluitType.objects.filter(catalogus=catalogus, omschrijving=params["besluittype"])

    if params["action"] == "status":
        present = zaaktypen.filter(concept=False).exists() and iots.exists() and besluittypen.exists()
        return {"present": bool(catalogus and present)}
    # zaaktype is a "foreign key or URL" field; _zaaktype is its local foreign key.
    Zaak.objects.filter(_zaaktype__in=zaaktypen).delete()
    zaaktypen.delete()
    iots.delete()
    besluittypen.delete()
    if params["action"] == "remove":
        return {"present": False}

    with transaction.atomic():  # all or nothing: a failure leaves no half zaaktype
        return _create(params, catalogus, datetime.datetime.now(tz=datetime.UTC).date())


def _create(params, catalogus, today):
    import datetime

    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import Eigenschap
    from openzaak.components.catalogi.models import EigenschapSpecificatie
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.catalogi.models import ResultaatType
    from openzaak.components.catalogi.models import RolType
    from openzaak.components.catalogi.models import StatusType
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
        doorlooptijd_behandeling=datetime.timedelta(days=30),
        opschorting_en_aanhouding_mogelijk=False,
        verlenging_mogelijk=False,
        publicatie_indicatie=False,
        verantwoordingsrelatie=[],
        producten_of_diensten=[],
        referentieproces_naam="podiumd-tests",
        datum_begin_geldigheid=today,
        versiedatum=today,
        concept=False,
    )
    iot = InformatieObjectType.objects.create(
        catalogus=catalogus,
        omschrijving=params["iot_omschrijving"],
        informatieobjectcategorie="podiumd-tests",
        vertrouwelijkheidaanduiding="openbaar",
        datum_begin_geldigheid=today,
        concept=False,
    )
    ZaakTypeInformatieObjectType.objects.create(
        zaaktype=zaaktype, informatieobjecttype=iot, volgnummer=1, richting="inkomend"
    )
    for number, omschrijving in enumerate(STATUSTYPEN, start=1):
        # informeren: OMC mails the initiator on each status (TA seed-minimal).
        StatusType.objects.create(
            zaaktype=zaaktype, statustype_omschrijving=omschrijving, statustypevolgnummer=number, informeren=True
        )
    for omschrijving, generiek in ROLTYPEN:
        RolType.objects.create(zaaktype=zaaktype, omschrijving=omschrijving, omschrijving_generiek=generiek)
    specificatie = EigenschapSpecificatie.objects.create(formaat="tekst", lengte="20", kardinaliteit="1")
    Eigenschap.objects.create(
        zaaktype=zaaktype, eigenschapnaam="kenteken", definitie="Kenteken", specificatie_van_eigenschap=specificatie
    )
    besluittype = BesluitType.objects.create(
        catalogus=catalogus,
        omschrijving=params["besluittype"],
        besluitcategorie="podiumd-tests",
        reactietermijn=datetime.timedelta(days=14),
        publicatie_indicatie=False,
        datum_begin_geldigheid=today,
        concept=False,
    )
    besluittype.zaaktypen.add(zaaktype)
    return {"present": True, "notes": _resultaattype(zaaktype, ResultaatType)}


def _resultaattype(zaaktype, resultaattype_model):
    """Create a resultaattype from the first 2020 selectielijst procestype; notes when that is not possible."""
    import datetime

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
    resultaattype_model.objects.create(
        zaaktype=zaaktype,
        omschrijving="Afgehandeld",
        resultaattypeomschrijving=omschrijving["url"],
        selectielijstklasse=resultaat["url"],
        archiefnominatie="vernietigen",
        archiefactietermijn=datetime.timedelta(days=3650),
        brondatum_archiefprocedure_afleidingswijze="afgehandeld",
    )
    return []
