"""Bootstrap step in Open Zaak: a published test zaaktype with an informatieobjecttype in the test catalogus.

Actions: status, apply (recreates), remove (also the zaken of the zaaktype).
Params: action, domein, rsin, identificatie, iot_omschrijving.
"""

STATUSTYPEN = ("Ingediend", "In behandeling", "Afgehandeld")
ROLTYPEN = (("Initiator", "initiator"), ("Behandelaar", "behandelaar"))


def run(params):
    import datetime

    from openzaak.components.catalogi.models import Catalogus
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.catalogi.models import RolType
    from openzaak.components.catalogi.models import StatusType
    from openzaak.components.catalogi.models import ZaakType
    from openzaak.components.catalogi.models import ZaakTypeInformatieObjectType
    from openzaak.components.zaken.models import Zaak

    catalogus = Catalogus.objects.filter(domein=params["domein"], rsin=params["rsin"]).first()
    zaaktypen = ZaakType.objects.filter(catalogus=catalogus, identificatie=params["identificatie"])
    iots = InformatieObjectType.objects.filter(catalogus=catalogus, omschrijving=params["iot_omschrijving"])

    if params["action"] == "status":
        return {"present": bool(catalogus and zaaktypen.filter(concept=False).exists() and iots.exists())}
    # zaaktype is a "foreign key or URL" field; _zaaktype is its local foreign key.
    Zaak.objects.filter(_zaaktype__in=zaaktypen).delete()
    zaaktypen.delete()
    iots.delete()
    if params["action"] == "remove":
        return {"present": False}

    today = datetime.datetime.now(tz=datetime.UTC).date()
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
    return {"present": True, "zaaktype": str(zaaktype.uuid), "informatieobjecttype": str(iot.uuid)}
