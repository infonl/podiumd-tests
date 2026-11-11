"""Run-tagged catalogus types in Open Zaak's test catalogus: list or delete them, published ones too.

The Catalogi API refuses to delete a published type; tests that publish types delete them here.
Actions: list (params prefix: names starting with it), delete (params name). A zaaktype is named by its identificatie,
an informatieobjecttype and a besluittype by their omschrijving; the zaken of a deleted zaaktype go with it.
"""


def run(params):
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.catalogi.models import ZaakType

    catalogus = {"catalogus__domein": params["domein"], "catalogus__rsin": params["rsin"]}
    kinds = (
        (ZaakType, "identificatie"),
        (BesluitType, "omschrijving"),
        (InformatieObjectType, "omschrijving"),
    )
    if params["action"] == "list":
        return sorted(
            {
                str(name)
                for model, field in kinds
                for name in model.objects.filter(**{f"{field}__startswith": params["prefix"]}, **catalogus).values_list(
                    field, flat=True
                )
            }
        )
    from openzaak.components.zaken.models import Zaak

    # A zaak protects its zaaktype; the zaken of a throwaway zaaktype are test data too.
    zaaktypen = ZaakType.objects.filter(identificatie=params["name"], **catalogus)
    Zaak.objects.filter(_zaaktype__in=zaaktypen).delete()
    for model, field in kinds:
        model.objects.filter(**{field: params["name"]}, **catalogus).delete()
    return {"deleted": params["name"]}
