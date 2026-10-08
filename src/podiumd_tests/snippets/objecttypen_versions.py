"""Read-only: the status of each named objecttype's newest version. Params: names.

Returns {name: "published" / "draft" / ..., or None when Objecttypen has no such objecttype}.
"""


def run(params):
    from objecttypes.core.models import ObjectType

    found = {}
    for name in params["names"]:
        object_type = ObjectType.objects.filter(name=name).first()
        newest = object_type.versions.order_by("-version").first() if object_type else None
        found[name] = newest.status if newest else None
    return found
