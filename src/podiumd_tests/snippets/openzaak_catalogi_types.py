"""Run-tagged catalogus types in Open Zaak's catalogi: list or delete them, published ones too.

The Catalogi API refuses to delete a published type; tests that publish types delete them here.
Params catalogi: catalogus fields (domein, rsin) per catalogus whose types count. Actions: list (params prefix: names
starting with it), delete (params name). A zaaktype is named by its identificatie, an informatieobjecttype and a
besluittype by their omschrijving; the zaken of a deleted zaaktype go with it.
"""


def run(params):
    from django.db import models
    from openzaak.components.catalogi.models import BesluitType
    from openzaak.components.catalogi.models import InformatieObjectType
    from openzaak.components.catalogi.models import ZaakType

    catalogus = models.Q(pk__in=[])
    for fields in params["catalogi"]:
        catalogus |= models.Q(**{f"catalogus__{field}": value for field, value in fields.items()})
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
                for name in model.objects.filter(catalogus, **{f"{field}__startswith": params["prefix"]}).values_list(
                    field, flat=True
                )
            }
        )
    from openzaak.components.zaken.models import Zaak

    # A zaak protects its zaaktype; the zaken of a throwaway zaaktype are test data too.
    zaaktypen = ZaakType.objects.filter(catalogus, identificatie=params["name"])
    Zaak.objects.filter(_zaaktype__in=zaaktypen).delete()
    for model, field in kinds:
        model.objects.filter(catalogus, **{field: params["name"]}).delete()
    return {"deleted": params["name"]}
