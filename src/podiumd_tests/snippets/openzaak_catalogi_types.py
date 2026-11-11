"""Run-tagged catalogus types in Open Zaak's test catalogus: list or delete them, published ones too.

The Catalogi API refuses to delete a published type; tests that publish types delete them here.
Actions: list (params prefix: names starting with it), delete (params name). A zaaktype is named by its identificatie,
an informatieobjecttype and a besluittype by their omschrijving.
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
    for model, field in kinds:
        model.objects.filter(**{field: params["name"]}, **catalogus).delete()
    return {"deleted": params["name"]}
