"""Read-only: an objecttype Objecten knows. Params: name.

Returns {"url": ...} before Open Object (the objecttype in Objecttypen, through Objecten's service),
{"uuid": ...} in Open Object, which serves the objecttype itself, or {} when Objecten has none.
"""

# include: _objecttypes


def run(params):
    object_type = objecten_objecttype(params["name"])
    if object_type is None:
        return {}
    service = getattr(object_type, "service", None)
    if service is None:
        return {"uuid": str(object_type.uuid)}
    return {"url": f"{service.api_root.rstrip('/')}/objecttypes/{object_type.uuid}"}
