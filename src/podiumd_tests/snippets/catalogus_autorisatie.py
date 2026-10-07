"""Wiring in Open Zaak: rights on the test catalogus for a platform client (e.g. Open Formulieren's).

Actions: status, apply, remove. Params: action, client_id, domein, rsin, record
({"created": [CatalogusAutorisatie id, ...]}). A client with heeft_alle_autorisaties
needs nothing; otherwise apply adds a CatalogusAutorisatie per component it lacks, and
remove deletes only the recorded ones.
"""

COMPONENTS = {"zrc": "zaken.", "drc": "documenten."}


def run(params):
    from openzaak.components.autorisaties.models import CatalogusAutorisatie
    from openzaak.components.catalogi.models import Catalogus
    from vng_api_common.authorizations.models import Applicatie
    from vng_api_common.scopes import SCOPE_REGISTRY

    applicatie = Applicatie.objects.filter(client_ids__contains=[params["client_id"]]).first()
    catalogus = Catalogus.objects.filter(domein=params["domein"], rsin=params["rsin"]).first()
    record = params.get("record") or {}
    created = list(record.get("created", []))

    def covered(component):
        return (
            applicatie.heeft_alle_autorisaties
            or CatalogusAutorisatie.objects.filter(
                applicatie=applicatie, catalogus=catalogus, component=component
            ).exists()
        )

    if params["action"] == "status":
        return {"present": bool(applicatie and catalogus and all(covered(c) for c in COMPONENTS))}
    if params["action"] == "remove":
        CatalogusAutorisatie.objects.filter(id__in=created).delete()
        return {"present": False}
    if applicatie is None or catalogus is None:
        msg = f"no Applicatie for client {params['client_id']} or no test catalogus"
        raise LookupError(msg)
    labels = {scope.label for scope in SCOPE_REGISTRY}
    for component, prefix in COMPONENTS.items():
        if not covered(component):
            row = CatalogusAutorisatie.objects.create(
                applicatie=applicatie,
                catalogus=catalogus,
                component=component,
                scopes=sorted(label for label in labels if label.startswith(prefix)),
                max_vertrouwelijkheidaanduiding="zeer_geheim",
            )
            created.append(row.id)
    return {"present": True, "record": {"created": created}}
