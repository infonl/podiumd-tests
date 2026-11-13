"""An objecttype in Objecttypen with a published version 1 of a JSON schema.

Actions: status, apply (recreates it unless present), remove; in Open Object its objects go with it.
Params: action, name, schema; optional uuid, the objecttype's fixed uuid (another uuid makes it missing).
Returns {"present": ..., "uuid": ...}; uuid is None when Objecttypen has no objecttype of that name (and uuid).
"""

# include: _objecttypes


def run(params):
    import datetime as dt

    object_type_model, version_model = objecttype_models()

    named = object_type_model.objects.filter(name=params["name"])
    found = (named.filter(uuid=params["uuid"]) if params.get("uuid") else named).first()
    present = found is not None and _published_schema(found) == params["schema"]
    if params["action"] == "status" or (params["action"] == "apply" and present):
        return {"present": present, "uuid": str(found.uuid) if found else None}
    taken = object_type_model.objects.filter(uuid=params["uuid"]) if params.get("uuid") else named.none()
    _delete(object_type_model, named | taken)
    if params["action"] == "remove":
        return {"present": False, "uuid": None}
    fixed = {"uuid": params["uuid"]} if params.get("uuid") else {}
    object_type = object_type_model.objects.create(name=params["name"], name_plural=params["name"], **fixed)
    today = dt.datetime.now(tz=dt.UTC).date()
    version_model.objects.create(
        object_type=object_type, version=1, json_schema=params["schema"], status="published", published_at=today
    )
    return {"present": True, "uuid": str(object_type.uuid)}


def _published_schema(object_type):
    newest = object_type.versions.order_by("-version").first()
    return newest.json_schema if newest and newest.status == "published" else None


def _delete(object_type_model, object_types):
    """Delete the objecttypes; in Open Object first their objects, which protect them."""
    if object_type_model.__module__.startswith("objects."):
        from objects.core.models import Object

        Object.objects.filter(object_type__in=object_types).delete()
    object_types.delete()
