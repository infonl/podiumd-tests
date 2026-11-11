"""Bootstrap step in Open Zaak: a published informatieobjecttype in the test catalogus, linked to no zaaktype.

Actions: status, apply (keeps an existing one), remove (also its documents). Params: action, domein, rsin, omschrijving.
"""


def run(params):
    import datetime as dt

    from openzaak.components.catalogi.models import Catalogus
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.documenten.models import EnkelvoudigInformatieObject

    catalogus = Catalogus.objects.filter(domein=params["domein"], rsin=params["rsin"]).first()
    iots = InformatieObjectType.objects.filter(catalogus=catalogus, omschrijving=params["omschrijving"])
    if params["action"] == "status":
        return {"present": iots.filter(concept=False).exists()}
    if params["action"] == "remove":
        # Documents protect their informatieobjecttype; one per canonical deletes all its versions.
        documents = EnkelvoudigInformatieObject.objects.filter(_informatieobjecttype__in=iots)
        canonicals = {document.canonical for document in documents}
        for canonical in canonicals:
            canonical.delete()
        iots.delete()
        return {"present": False}
    if not iots.filter(concept=False).exists():
        InformatieObjectType.objects.create(
            catalogus=catalogus,
            omschrijving=params["omschrijving"],
            informatieobjectcategorie="podiumd-tests",
            vertrouwelijkheidaanduiding="openbaar",
            datum_begin_geldigheid=dt.datetime.now(tz=dt.UTC).date(),
            concept=False,
        )
    return {"present": True}
