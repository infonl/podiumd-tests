"""Bootstrap step: a ZGW JWT client of the suite (vng_api_common Applicatie and JWTSecret).

Actions: status, apply (replaces the client), remove. Params: action, client_id,
secret (apply only), scopes ({component: [scope, ...]}, plain autorisaties), and in
Open Zaak optionally catalogus, rights limited to the test catalogus (PLAN.md §11a):
{domein, rsin, owns (creates the catalogus; on remove deletes it with all its zaken),
components ({component: [scope prefix, ...]}), exclude (scope words left out), max_va}.
"""


def run(params):
    from vng_api_common.authorizations.models import Applicatie
    from vng_api_common.authorizations.models import Autorisatie
    from vng_api_common.models import JWTSecret

    client_id = params["client_id"]
    applicaties = Applicatie.objects.filter(client_ids__contains=[client_id])
    secrets = JWTSecret.objects.filter(identifier=client_id)
    catalogus_params = params.get("catalogus")
    if params["action"] == "status":
        present = applicaties.exists() and secrets.exists()
        return {"present": bool(present and (not catalogus_params or _catalogi(catalogus_params).exists()))}
    if params["action"] == "remove":
        removed = applicaties.delete()[0] + secrets.delete()[0]
        if catalogus_params and catalogus_params["owns"]:
            removed += _remove_catalogus(catalogus_params)
        return {"removed": removed}
    applicaties.delete()
    applicatie = Applicatie.objects.create(label=client_id, client_ids=[client_id], heeft_alle_autorisaties=False)
    for component, scopes in params["scopes"].items():
        if scopes:
            Autorisatie.objects.create(applicatie=applicatie, component=component, scopes=scopes)
    if catalogus_params:
        _catalogus_autorisaties(applicatie, catalogus_params)
    JWTSecret.objects.update_or_create(identifier=client_id, defaults={"secret": params["secret"]})
    return {"present": True}


def _catalogi(catalogus_params):
    from openzaak.components.catalogi.models import Catalogus

    return Catalogus.objects.filter(domein=catalogus_params["domein"], rsin=catalogus_params["rsin"])


def _remove_catalogus(catalogus_params):
    from openzaak.components.zaken.models import Zaak

    catalogi = _catalogi(catalogus_params)
    # zaaktype is a "foreign key or URL" field; _zaaktype is its local foreign key.
    Zaak.objects.filter(_zaaktype__catalogus__in=catalogi).delete()
    return catalogi.delete()[0]


def _catalogus_autorisaties(applicatie, catalogus_params):
    from openzaak.components.autorisaties.models import CatalogusAutorisatie
    from openzaak.components.catalogi.models import Catalogus
    from vng_api_common.scopes import SCOPE_REGISTRY

    if catalogus_params["owns"]:
        catalogus, _ = Catalogus.objects.get_or_create(
            domein=catalogus_params["domein"],
            rsin=catalogus_params["rsin"],
            defaults={"naam": "podiumd-tests", "contactpersoon_beheer_naam": "podiumd-tests"},
        )
    else:
        catalogus = _catalogi(catalogus_params).get()
    labels = {scope.label for scope in SCOPE_REGISTRY}
    excluded = catalogus_params["exclude"]
    for component, prefixes in catalogus_params["components"].items():
        scopes = sorted(
            label for label in labels if label.startswith(tuple(prefixes)) and not any(w in label for w in excluded)
        )
        if scopes:
            CatalogusAutorisatie.objects.create(
                applicatie=applicatie,
                catalogus=catalogus,
                component=component,
                scopes=scopes,
                max_vertrouwelijkheidaanduiding=catalogus_params["max_va"],
            )
