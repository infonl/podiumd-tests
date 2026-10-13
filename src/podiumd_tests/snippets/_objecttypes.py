"""Included by snippets with `# include: _objecttypes`: objecttype models before and after Open Object.

Open Object (podiumd 4.10) merges Objecten and Objecttypen into one app; podiumd 4.9 runs them apart.
"""


def objecttype_models():
    """(ObjectType, its version model) of this app's Objecttypen API."""
    try:
        from objecttypes.core.models import ObjectType
        from objecttypes.core.models import ObjectVersion
    except ImportError:
        from objects.core.models import ObjectType
        from objects.core.models import ObjectTypeVersion as ObjectVersion
    return ObjectType, ObjectVersion


def objecten_name_field():
    """Field of Objecten's ObjectType with the objecttype's name: before Open Object, _name holds a copy."""
    from objects.core.models import ObjectType

    return "_name" if any(f.name == "_name" for f in ObjectType._meta.get_fields()) else "name"


def objecten_objecttype(name):
    """Objecten's ObjectType of this name, or None."""
    from objects.core.models import ObjectType

    return ObjectType.objects.filter(**{objecten_name_field(): name}).first()
