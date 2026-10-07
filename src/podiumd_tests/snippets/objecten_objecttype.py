"""Read-only: the URL Objecten knows an objecttype by. Params: name. Returns {"url": ... or None}."""


def run(params):
    from objects.core.models import ObjectType

    object_type = ObjectType.objects.filter(_name=params["name"]).first()
    if object_type is None:
        return {"url": None}
    return {"url": f"{object_type.service.api_root.rstrip('/')}/objecttypes/{object_type.uuid}"}
