"""Bootstrap step: an API token (TokenAuth) in Open Klant, Objecttypen or Objecten.

Actions: status, apply (replaces the token), remove. Params: action, modules (token models
modules to try, in order), identifier, secret (the token; apply only), objecttypen_api (the token
is for the Objecttypen API), and for Objecten object_types: names of objecttypes the token may
read and write; status also checks that the token has a permission on every objecttype of those names.
"""

# include: _objecttypes


def run(params):
    token_auth = _token_model(params["modules"])
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
        # Open Object grants its Objecttypen API per objecttype or to a superuser token.
        **({"is_superuser": True} if params.get("objecttypen_api") and hasattr(token_auth, "is_superuser") else {}),
    )
    return {"present": True, "notes": _permissions(token, params.get("object_types") or [])}


def _permissions(token, names):
    if not names:
        return []
    from objects.core.models import ObjectType
    from objects.token.models import Permission

    name_field = objecten_name_field()
    object_types = ObjectType.objects.filter(**{f"{name_field}__in": names})
    for object_type in object_types:
        Permission.objects.create(token_auth=token, object_type=object_type, mode="read_and_write")
    found = set(object_types.values_list(name_field, flat=True))
    return [f"no objecttype {n}" for n in sorted(set(names) - found)]


def _missing(token, names):
    # A deleted objecttype takes its permissions along; a new one of the same name has none yet.
    if not names:
        return []
    from objects.core.models import ObjectType

    granted = set(token.permissions.values_list("object_type__pk", flat=True))
    object_types = ObjectType.objects.filter(**{f"{objecten_name_field()}__in": names})
    return [o.pk for o in object_types if o.pk not in granted]


def _token_model(modules):
    # Objecttypen's own token model is gone in Open Object, whose single TokenAuth serves both APIs.
    import importlib.util

    for module in modules:
        if importlib.util.find_spec(module.split(".")[0]):
            return importlib.import_module(module).TokenAuth
    raise ImportError(", ".join(modules))
