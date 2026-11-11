"""Bootstrap step in Open Zaak: the test besluittype allows the test informatieobjecttype, so a besluit can hold a document.

A step of its own: adding the link in openzaak_zaaktype would make that step missing on bootstrapped environments,
and its apply recreates the zaaktypen, which ZAC's BPMN link of the BPMN zaaktype does not survive.
Actions: status, apply, remove. Params: action, domein, rsin, besluittype, iot (omschrijvingen).
"""


def run(params):
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import InformatieObjectType

    catalogus = {"catalogus__domein": params["domein"], "catalogus__rsin": params["rsin"]}
    besluittypen = BesluitType.objects.filter(omschrijving=params["besluittype"], **catalogus)
    iots = InformatieObjectType.objects.filter(omschrijving=params["iot"], **catalogus)
    if params["action"] == "status":
        return {"present": besluittypen.filter(informatieobjecttypen__in=iots).exists()}
    for besluittype in besluittypen:
        if params["action"] == "remove":
            besluittype.informatieobjecttypen.remove(*iots)
        else:
            besluittype.informatieobjecttypen.add(*iots)
    return {"present": params["action"] != "remove" and besluittypen.exists() and iots.exists()}
