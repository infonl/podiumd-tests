"""Bootstrap step: a ZGW JWT client of the suite (vng_api_common Applicatie and JWTSecret).

Actions: status, apply (replaces the client), remove. Params: action, client_id,
secret (apply only), scopes ({component: [scope, ...]}, plain autorisaties), and in
Open Zaak optionally catalogus, rights limited to the test catalogus (PLAN.md §11a):
{domein, rsin, owns (creates the catalogus; on remove deletes it with all its zaken),
components ({component: [scope prefix, ...]}), exclude (scope words left out), max_va}; and
optionally zaaktypen, Zaken API rights on every version of zaaktypen the environment owns:
{identificaties, scopes, max_va}.
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
        if catalogus_params and not _catalogi(catalogus_params).exists():
            present = False
        if (
            params.get("zaaktypen")
            and not Autorisatie.objects.filter(applicatie__in=applicaties, component="zrc").exists()
        ):
            present = False
        return {"present": bool(present)}
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
    notes = _zaaktype_autorisaties(applicatie, params["zaaktypen"]) if params.get("zaaktypen") else []
    JWTSecret.objects.update_or_create(identifier=client_id, defaults={"secret": params["secret"]})
    return {"present": True, "notes": notes}


def _zaaktype_autorisaties(applicatie, zaaktypen_params):
    from openzaak.components.catalogi.models import ZaakType
    from openzaak.utils import build_absolute_url
    from vng_api_common.authorizations.models import Autorisatie

    wanted = zaaktypen_params["identificaties"]
    found = ZaakType.objects.filter(identificatie__in=wanted, concept=False)
    for zaaktype in found:
        # Open Zaak resolves a local zaaktype URL by its path; the host must be in ALLOWED_HOSTS.
        Autorisatie.objects.create(
            applicatie=applicatie,
            component="zrc",
            zaaktype=build_absolute_url(zaaktype.get_absolute_api_url()),
            scopes=zaaktypen_params["scopes"],
            max_vertrouwelijkheidaanduiding=zaaktypen_params["max_va"],
        )
    missing = sorted(set(wanted) - {z.identificatie for z in found})
    return [f"no published zaaktype {i}" for i in missing]


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
    import importlib

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
    # Open Zaak registers an API's scopes when its scopes module is imported; a shell imports none.
    for component in ("zaken", "documenten", "besluiten", "catalogi", "autorisaties"):
        importlib.import_module(f"openzaak.components.{component}.api.scopes")
    # Atomic scopes only: a scope with children is a combination such as "zaken.aanmaken | zaken.bijwerken".
    labels = {scope.label for scope in SCOPE_REGISTRY if not getattr(scope, "children", None)}
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
