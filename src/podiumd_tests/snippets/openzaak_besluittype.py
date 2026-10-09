"""Bootstrap step in Open Zaak: a published test besluittype for an environment's zaaktype, which ZAC's
inrichtingscheck requires.

Actions: status, apply (recreates), remove. Params: action, omschrijving, zaaktype (identificatie;
empty: the profile does not allow it, nothing to do). The besluittype goes in the zaaktype's catalogus
and is linked to every version of it.
"""


def run(params):
    import datetime

    from django.utils import timezone
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import ZaakType

    besluittypen = BesluitType.objects.filter(omschrijving=params["omschrijving"])
    zaaktypen = (
        ZaakType.objects.filter(identificatie=params["zaaktype"]) if params["zaaktype"] else ZaakType.objects.none()
    )
    if params["action"] == "status":
        return {"present": not params["zaaktype"] or besluittypen.filter(zaaktypen__in=zaaktypen).exists()}
    besluittypen.delete()
    if params["action"] == "remove" or not zaaktypen.exists():
        return {"present": params["action"] != "remove"}
    besluittype = BesluitType.objects.create(
        catalogus=zaaktypen.first().catalogus,
        omschrijving=params["omschrijving"],
        besluitcategorie="podiumd-tests",
        reactietermijn=datetime.timedelta(days=14),
        publicatie_indicatie=False,
        datum_begin_geldigheid=timezone.localdate(),
        concept=False,
    )
    besluittype.zaaktypen.add(*zaaktypen)
    return {"present": True}
