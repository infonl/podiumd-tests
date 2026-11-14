"""Open Formulieren's service for Referentielijsten, which a select field names as its options source.

Open Formulieren allows one service per API root: an existing one is used and kept. Actions: status, apply,
remove (the suite's own only). Params: action, prefix, api_root. Returns present and the service's slug.
"""


def run(params):
    from zgw_consumers.constants import APITypes
    from zgw_consumers.constants import AuthTypes
    from zgw_consumers.models import Service

    slug = f"{params['prefix']}-referentielijsten"
    if params["action"] == "remove":
        Service.objects.filter(slug=slug).delete()
        return {"present": False, "slug": ""}
    service = Service.objects.filter(api_root=params["api_root"]).first()
    if service is None and params["action"] == "apply":
        service = Service.objects.create(
            slug=slug,
            label="Referentielijsten (podiumd-tests)",
            api_type=APITypes.orc,
            api_root=params["api_root"],
            auth_type=AuthTypes.no_auth,
        )
    return {"present": service is not None, "slug": service.slug if service else ""}
