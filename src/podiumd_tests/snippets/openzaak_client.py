"""Bootstrap step in Open Zaak: the suite's ZGW client, limited to its own test catalogus.

Actions: status, apply (idempotent; replaces stale objects), remove (also
everything left in the test catalogus). Params: action, client_id, label,
domein, rsin, secret (apply only).
"""

# Scope prefix per component the client gets on its own catalogus (PLAN.md §11a: no heeft_alle_autorisaties).
CATALOGUS_COMPONENTS = {"zrc": "zaken.", "drc": "documenten.", "brc": "besluiten."}
CATALOGI_SCOPES = ["catalogi.lezen", "catalogi.schrijven"]


def run(params):
    from openzaak.components.autorisaties.models import CatalogusAutorisatie
    from openzaak.components.catalogi.models import Catalogus
    from openzaak.components.zaken.models import Zaak
    from vng_api_common.authorizations.models import Applicatie
    from vng_api_common.authorizations.models import Autorisatie
    from vng_api_common.models import JWTSecret
    from vng_api_common.scopes import SCOPE_REGISTRY

    client_id = params["client_id"]
    applicaties = Applicatie.objects.filter(client_ids__contains=[client_id])
    catalogi = Catalogus.objects.filter(domein=params["domein"], rsin=params["rsin"])
    action = params["action"]

    if action == "status":
        catalogus = catalogi.first()
        return {
            "applicatie": applicaties.exists(),
            "secret": JWTSecret.objects.filter(identifier=client_id).exists(),
            "catalogus": str(catalogus.uuid) if catalogus else None,
        }

    if action == "remove":
        # zaaktype is a "foreign key or URL" field; _zaaktype is its local foreign key.
        Zaak.objects.filter(_zaaktype__catalogus__in=catalogi).delete()
        return {
            "catalogi": catalogi.delete()[0],
            "applicaties": applicaties.delete()[0],
            "secrets": JWTSecret.objects.filter(identifier=client_id).delete()[0],
        }

    # apply
    catalogus, _ = Catalogus.objects.get_or_create(
        domein=params["domein"],
        rsin=params["rsin"],
        defaults={"naam": params["label"], "contactpersoon_beheer_naam": "podiumd-tests"},
    )
    applicaties.delete()
    applicatie = Applicatie.objects.create(label=params["label"], client_ids=[client_id], heeft_alle_autorisaties=False)
    Autorisatie.objects.create(applicatie=applicatie, component="ztc", scopes=CATALOGI_SCOPES)
    labels = {scope.label for scope in SCOPE_REGISTRY}
    for component, prefix in CATALOGUS_COMPONENTS.items():
        scopes = sorted(label for label in labels if label.startswith(prefix))
        if scopes:
            CatalogusAutorisatie.objects.create(
                applicatie=applicatie,
                catalogus=catalogus,
                component=component,
                scopes=scopes,
                max_vertrouwelijkheidaanduiding="zeer_geheim",
            )
    JWTSecret.objects.update_or_create(identifier=client_id, defaults={"secret": params["secret"]})
    return {"catalogus": str(catalogus.uuid)}
