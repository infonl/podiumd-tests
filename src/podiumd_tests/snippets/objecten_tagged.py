"""Volume data in Objecten of an objecttype the environment has (seed-volume): VAC, Kennisartikel.

Params: action (count, create, delete), name of the objecttype, key and prefix: an object is
volume data when record data[key] starts with prefix; for create also items, the data of each new
object. Returns {"count": ...} afterwards; 0 when Objecten has no such objecttype.
"""


def run(params):
    import datetime

    from django.db import transaction
    from objects.core.models import Object
    from objects.core.models import ObjectRecord
    from objects.core.models import ObjectType

    object_type = ObjectType.objects.filter(_name=params["name"]).first()
    if object_type is None:
        return {"count": 0}
    marked = {f"data__{params['key']}__startswith": params["prefix"]}
    tagged = Object.objects.filter(object_type=object_type, records__in=ObjectRecord.objects.filter(**marked))
    if params["action"] == "delete":
        with transaction.atomic():
            ObjectRecord.objects.filter(object__in=tagged).delete()
            Object.objects.filter(pk__in=tagged.values("pk")).delete()
    if params["action"] == "create":
        today = datetime.datetime.now(tz=datetime.UTC).date()
        with transaction.atomic():
            for data in params["items"]:
                obj = Object.objects.create(object_type=object_type)
                ObjectRecord.objects.create(
                    object=obj,
                    index=1,
                    version=1,
                    data=data,
                    start_at=today,
                    registration_at=today,
                    _object_type=object_type,
                )
    return {"count": tagged.distinct().count()}
