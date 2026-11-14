"""Read-only: the Objecten token of Open Formulieren's Objects API group on an API root. Params: api_root.

Returns {"token": ...}, "" when no group uses that API root with an API key.
"""


def run(params):
    from openforms.contrib.objects_api.models import ObjectsAPIGroupConfig

    group = ObjectsAPIGroupConfig.objects.filter(objects_service__api_root=params["api_root"]).first()
    header = group.objects_service.header_value if group else ""
    return {"token": header.removeprefix("Token ").strip()}
