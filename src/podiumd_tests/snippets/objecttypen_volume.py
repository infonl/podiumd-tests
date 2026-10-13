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


# include: _objecttypes


def run(params):
    import datetime as dt

    object_type_model, version_model = objecttype_models()

    if params["action"] == "remove":
        object_type_model.objects.filter(name=params["name"]).delete()
        return {"uuid": None}
    object_type = object_type_model.objects.filter(name=params["name"]).first()
    if params["action"] == "status":
        return {"uuid": str(object_type.uuid) if object_type else None}
    if object_type is None:
        object_type = object_type_model.objects.create(name=params["name"], name_plural=params["name"])
        today = dt.datetime.now(tz=dt.UTC).date()
        version_model.objects.create(
            object_type=object_type, version=1, json_schema=SCHEMA, status="published", published_at=today
        )
    return {"uuid": str(object_type.uuid)}
