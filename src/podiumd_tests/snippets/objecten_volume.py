"""Volume data in Objecten (seed-volume): objects of the volume objecttype.

Params: action (count, create, delete), uuid and name of the objecttype; for create also start,
stop and tag. create registers the objecttype (through Objecten's objecttypes service) and adds
objects start..stop-1 in one transaction; delete removes the objects and the registration.
Returns {"count": ...} afterwards.
"""


def run(params):
    import datetime

    from django.db import transaction
    from objects.core.models import Object
    from objects.core.models import ObjectRecord
    from objects.core.models import ObjectType
    from zgw_consumers.models import Service

    registered = ObjectType.objects.filter(uuid=params["uuid"]).first() if params["uuid"] else None
    if params["action"] == "delete" and registered:
        with transaction.atomic():
            ObjectRecord.objects.filter(object__object_type=registered).delete()
            Object.objects.filter(object_type=registered).delete()
            registered.delete()
        return {"count": 0}
    if params["action"] == "create":
        if registered is None:
            service = Service.objects.filter(api_root__contains="objecttype").first()
            registered = ObjectType.objects.create(
                service=service, uuid=params["uuid"], _name=params["name"], name=params["name"]
            )
        today = datetime.datetime.now(tz=datetime.UTC).date()
        with transaction.atomic():
            for seq in range(params["start"], params["stop"]):
                obj = Object.objects.create(object_type=registered)
                data = {"title": f"{params['tag']} {seq}", "body": params["body"], "seq": seq, "tag": params["tag"]}
                ObjectRecord.objects.create(
                    object=obj,
                    index=1,
                    version=1,
                    data=data,
                    start_at=today,
                    registration_at=today,
                    _object_type=registered,
                )
    count = Object.objects.filter(object_type=registered).count() if registered else 0
    return {"count": count}
