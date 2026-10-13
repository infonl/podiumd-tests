"""Read-only: the status of each named objecttype's newest version. Params: names.

Returns {name: "published" / "draft" / ..., or None when Objecttypen has no such objecttype}.
"""

# include: _objecttypes


def run(params):
    object_type_model, _ = objecttype_models()

    found = {}
    for name in params["names"]:
        object_type = object_type_model.objects.filter(name=name).first()
        newest = object_type.versions.order_by("-version").first() if object_type else None
        found[name] = newest.status if newest else None
    return found
