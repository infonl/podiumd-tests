"""An objecttype in Objecttypen with a published version 1 of a JSON schema.

Actions: status, apply (recreates it unless present), remove; in Open Object its objects and permissions go with it.
Params: action, name, schema; optional uuid, the objecttype's fixed uuid (another uuid makes it missing); optional
grants, {key of an Objecten token: mode (read_only, read_and_write)} to give on it (Open Object only; status checks
them).
Returns {"present": ..., "uuid": ...}; uuid is None when Objecttypen has no objecttype of that name (and uuid).
"""

# include: _objecttypes


def run(params):
    object_type_model, version_model = objecttype_models()

    named = object_type_model.objects.filter(name=params["name"])
    found = (named.filter(uuid=params["uuid"]) if params.get("uuid") else named).first()
    present = found is not None and _published_schema(found) == params["schema"]
    grants = params.get("grants") or {}
    if params["action"] == "status":
        granted = not present or not _missing_grants(found, grants)
        return {"present": present and granted, "uuid": str(found.uuid) if found else None}
    if params["action"] == "apply" and present:
        return {"present": True, "uuid": str(found.uuid), "notes": _grant(found, grants)}
    taken = object_type_model.objects.filter(uuid=params["uuid"]) if params.get("uuid") else named.none()
    _delete(object_type_model, named | taken)
    if params["action"] == "remove":
        return {"present": False, "uuid": None}
    object_type = _create(object_type_model, version_model, params)
    return {"present": True, "uuid": str(object_type.uuid), "notes": _grant(object_type, grants)}


def _create(object_type_model, version_model, params):
    """Create the objecttype with its published version 1."""
    import datetime as dt

    fixed = {"uuid": params["uuid"]} if params.get("uuid") else {}
    object_type = object_type_model.objects.create(name=params["name"], name_plural=params["name"], **fixed)
    today = dt.datetime.now(tz=dt.UTC).date()
    version_model.objects.create(
        object_type=object_type, version=1, json_schema=params["schema"], status="published", published_at=today
    )
    return object_type


def _published_schema(object_type):
    newest = object_type.versions.order_by("-version").first()
    return newest.json_schema if newest and newest.status == "published" else None


def _tokens(object_type, grants):
    """Return (token, mode) of each granted key that is an Objecten token; none outside Open Object."""
    if not grants or not object_type.__module__.startswith("objects."):
        return []
    from objects.token.models import TokenAuth

    tokens = TokenAuth.objects.filter(token__in=list(grants))
    return [(token, grants[token.token]) for token in tokens]


def _missing_grants(object_type, grants):
    return [
        token
        for token, mode in _tokens(object_type, grants)
        if not token.permissions.filter(object_type=object_type, mode=mode).exists()
    ]


def _grant(object_type, grants):
    """Give each granted token its mode on the objecttype; notes on what could not be granted."""
    if not grants:
        return []
    from objects.token.models import Permission

    tokens = _tokens(object_type, grants)
    for token, mode in tokens:
        Permission.objects.update_or_create(token_auth=token, object_type=object_type, defaults={"mode": mode})
    missing = len(grants) - len(tokens)
    return [f"{missing} granted key(s) are no Objecten token in this app: grant them by hand"] if missing else []


def _delete(object_type_model, object_types):
    """Delete the objecttypes; in Open Object first their objects, which protect them."""
    if object_type_model.__module__.startswith("objects."):
        from objects.core.models import Object

        Object.objects.filter(object_type__in=object_types).delete()
    object_types.delete()
