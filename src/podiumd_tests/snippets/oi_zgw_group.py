"""Wiring W4 in Open Inwoner: an API group over the environment's Open Zaak services, so zaken show.

TA seed-oi-bedrading.sh. The services (and Open Inwoner's own client) are the environment's;
the group is the suite's. Actions: status, apply, remove. Params: action, name, zaken_url
(Open Zaak's zaken API root as Open Inwoner calls it), record ({"group": pk}).
"""


def run(params):
    from open_inwoner.openzaak.models import ZGWApiGroupConfig

    groups = ZGWApiGroupConfig.objects.filter(name=params["name"])
    if params["action"] == "status":
        return {"present": groups.exists()}
    record = params.get("record") or {}
    if params["action"] == "remove":
        ZGWApiGroupConfig.objects.filter(pk=record.get("group")).delete()
        return {"present": False}
    group = groups.first() or _create(params)
    return {"present": True, "record": {"group": group.pk}}


def _create(params):
    from open_inwoner.openzaak.models import OpenZaakConfig
    from open_inwoner.openzaak.models import ZGWApiGroupConfig
    from zgw_consumers.models import Service

    zaken = Service.objects.get(api_root=params["zaken_url"])
    root = params["zaken_url"].removesuffix("zaken/api/v1/")
    return ZGWApiGroupConfig.objects.create(
        name=params["name"],
        open_zaak_config=OpenZaakConfig.get_solo(),
        zrc_service=zaken,
        drc_service=Service.objects.get(api_root=root + "documenten/api/v1/"),
        ztc_service=Service.objects.get(api_root=root + "catalogi/api/v1/"),
        # Zaken of an eHerkenning login through Open Zaak 1.20+ filters (TA 141).
        fetch_eherkenning_zaken_with_openzaak_120_params=True,
        # No cached zaak lists: a test's new zaak shows at once.
        cache_zaken_timeout=0,
    )
