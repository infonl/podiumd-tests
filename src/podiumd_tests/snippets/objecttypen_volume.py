"""Volume data in Objecttypen (seed-volume): the volume objecttype. Params: action (status, apply, remove), name.

Returns {"uuid": ...} of the objecttype, None when absent. apply first makes it, with a published
version 1 (title, body, seq, tag); remove deletes it.
"""

SCHEMA = {
    "type": "object",
    "title": "podiumd-tests volume",
    "$schema": "http://json-schema.org/draft-07/schema#",
    "required": ["title", "tag"],
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "seq": {"type": "integer"},
        "tag": {"type": "string"},
    },
}


def run(params):
    import datetime

    from objecttypes.core.models import ObjectType
    from objecttypes.core.models import ObjectVersion

    if params["action"] == "remove":
        ObjectType.objects.filter(name=params["name"]).delete()
        return {"uuid": None}
    object_type = ObjectType.objects.filter(name=params["name"]).first()
    if params["action"] == "status":
        return {"uuid": str(object_type.uuid) if object_type else None}
    if object_type is None:
        object_type = ObjectType.objects.create(name=params["name"], name_plural=params["name"])
        today = datetime.datetime.now(tz=datetime.UTC).date()
        ObjectVersion.objects.create(
            object_type=object_type, version=1, json_schema=SCHEMA, status="published", published_at=today
        )
    return {"uuid": str(object_type.uuid)}
