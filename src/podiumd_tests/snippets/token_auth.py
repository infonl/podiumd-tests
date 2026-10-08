"""Bootstrap step: an API token (TokenAuth) in Open Klant, Objecttypen or Objecten.

Actions: status, apply (replaces the token), remove. Params: action, module
(the app's token models module), identifier, secret (the token; apply only), and for
Objecten object_types: names of objecttypes the token may read and write; status also
checks that the token has a permission on every objecttype of those names.
"""


def run(params):
    import importlib

    token_auth = importlib.import_module(params["module"]).TokenAuth
    tokens = token_auth.objects.filter(identifier=params["identifier"])
    if params["action"] == "status":
        token = tokens.first()
        return {"present": token is not None and not _missing(token, params.get("object_types") or [])}
    if params["action"] == "remove":
        return {"removed": tokens.delete()[0]}
    tokens.delete()
    token = token_auth.objects.create(
        identifier=params["identifier"],
        token=params["secret"],
        contact_person="podiumd-tests",
        email="podiumd-tests@example.invalid",
    )
    return {"present": True, "notes": _permissions(token, params.get("object_types") or [])}


def _permissions(token, names):
    if not names:
        return []
    from objects.core.models import ObjectType
    from objects.token.models import Permission

    # _name is Objecten's stored copy of the objecttype's name in Objecttypen.
    object_types = ObjectType.objects.filter(_name__in=names)
    for object_type in object_types:
        Permission.objects.create(token_auth=token, object_type=object_type, mode="read_and_write")
    found = set(object_types.values_list("_name", flat=True))
    return [f"no objecttype {n}" for n in sorted(set(names) - found)]


def _missing(token, names):
    # A deleted objecttype takes its permissions along; a new one of the same name has none yet.
    if not names:
        return []
    from objects.core.models import ObjectType

    granted = set(token.permissions.values_list("object_type__pk", flat=True))
    return [o.pk for o in ObjectType.objects.filter(_name__in=names) if o.pk not in granted]
