"""Wiring in Open Formulieren: the ZGW API group with which test forms register zaken in the test catalogus.

Open Formulieren allows one service per API root, so existing services for Open Zaak's
API roots are reused (and with them the platform's own client; step
openzaak-of-autorisatie gives it rights on the test catalogus). Services are created,
on the suite's own ZGW client, only where none exists. Actions: status, apply (recreates),
remove (test objects only). Params: action, prefix (the group's identifier), openzaak_url
(as Open Formulieren reaches it), client_id, secret, domein, rsin.
"""


def run(params):
    from openforms.registrations.contrib.zgw_apis.models import ZGWApiGroupConfig
    from zgw_consumers.models import Service

    prefix = params["prefix"]
    groups = ZGWApiGroupConfig.objects.filter(identifier=prefix)
    services = Service.objects.filter(slug__startswith=f"{prefix}-")

    if params["action"] == "status":
        # A group on another Open Zaak URL (e.g. http before the switch to https) is stale.
        return {"present": groups.filter(zrc_service__api_root__startswith=params["openzaak_url"]).exists()}

    groups.delete()
    services.delete()
    if params["action"] == "remove":
        return {"present": False}

    created = {}
    for api_type, path in (("zrc", "zaken"), ("drc", "documenten"), ("ztc", "catalogi")):
        api_root = f"{params['openzaak_url']}/{path}/api/v1/"
        existing = Service.objects.filter(api_root=api_root).first()
        if existing is not None:
            created[api_type] = existing
            continue
        created[api_type] = Service.objects.create(
            slug=f"{prefix}-{api_type}",
            label=f"{prefix} {path}",
            api_type=api_type,
            api_root=api_root,
            auth_type="zgw",
            client_id=params["client_id"],
            secret=params["secret"],
            user_id=params["client_id"],
            user_representation=params["client_id"],
        )
    ZGWApiGroupConfig.objects.create(
        name=prefix,
        identifier=prefix,
        zrc_service=created["zrc"],
        drc_service=created["drc"],
        ztc_service=created["ztc"],
        catalogue_domain=params["domein"],
        catalogue_rsin=params["rsin"],
        organisatie_rsin=params["rsin"],
        auteur="podiumd-tests",
    )
    return {"present": True}
