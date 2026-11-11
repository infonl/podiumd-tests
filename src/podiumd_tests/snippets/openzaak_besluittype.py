"""Bootstrap step in Open Zaak: a published test besluittype for an environment's zaaktype, which ZAC's
inrichtingscheck requires.

Actions: status, apply (creates it or links it again), remove. Params: action, omschrijving, zaaktype (identificatie;
empty: the profile does not allow it, nothing to do). The besluittype goes in the zaaktype's catalogus
and is linked to every version of it, and to their informatieobjecttypen: a besluit can only link a document of
one of its besluittype's informatieobjecttypen.
"""


def run(params):
    import datetime as dt

    from django.utils import timezone
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import ZaakType

    besluittypen = BesluitType.objects.filter(omschrijving=params["omschrijving"])
    zaaktypen = (
        ZaakType.objects.filter(identificatie=params["zaaktype"]) if params["zaaktype"] else ZaakType.objects.none()
    )
    if params["action"] == "status":
        # Every published version: a zaaktype published after bootstrap is not linked yet.
        linked = set(besluittypen.values_list("zaaktypen", flat=True))
        published = zaaktypen.filter(concept=False)
        documenttypes = set(besluittypen.values_list("informatieobjecttypen", flat=True))
        wanted = set(_informatieobjecttypen(zaaktypen).values_list("pk", flat=True))
        return {
            "present": not params["zaaktype"]
            or (all(zaaktype.pk in linked for zaaktype in published) and wanted <= documenttypes)
        }
    if params["action"] == "remove" or not zaaktypen.exists():
        besluittypen.delete()
        return {"present": params["action"] != "remove"}
    # Kept, not recreated: ZAC and the test client's autorisaties know it by its URL.
    besluittype = besluittypen.first() or BesluitType.objects.create(
        catalogus=zaaktypen.first().catalogus,
        omschrijving=params["omschrijving"],
        besluitcategorie="podiumd-tests",
        reactietermijn=dt.timedelta(days=14),
        publicatie_indicatie=False,
        datum_begin_geldigheid=timezone.localdate(),
        concept=False,
    )
    besluittype.zaaktypen.add(*zaaktypen)
    besluittype.informatieobjecttypen.add(*_informatieobjecttypen(zaaktypen))
    return {"present": True}


def _informatieobjecttypen(zaaktypen):
    from openzaak.components.catalogi.models import InformatieObjectType

    return InformatieObjectType.objects.filter(zaaktypen__in=zaaktypen, concept=False).distinct()
