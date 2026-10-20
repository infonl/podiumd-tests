"""Read-only: every Objects API group, read through Open Formulieren's own clients. Params: none.

Returns [{group, errors}]; errors is [] when the group lists objects and objecttypes with its Services.
"""


def run(params):
    from openforms.contrib.objects_api.clients import get_objects_client
    from openforms.contrib.objects_api.clients import get_objecttypes_client
    from openforms.contrib.objects_api.models import ObjectsAPIGroupConfig

    del params  # run() takes params like every snippet; this one has none
    found = []
    for group in ObjectsAPIGroupConfig.objects.order_by("identifier"):
        errors = [
            *_error("objects", _list_objects, get_objects_client, group),
            *_error("objecttypes", _list_objecttypes, get_objecttypes_client, group),
        ]
        found.append({"group": group.identifier, "errors": errors})
    return found


def _list_objects(client):
    with client:
        client.get("objects", params={"pageSize": 1}, timeout=10).raise_for_status()


def _list_objecttypes(client):
    with client:
        client.list_objecttypes(page=1, page_size=1)


def _error(name, read, client_for, group):
    try:
        read(client_for(group))
    except Exception as exc:  # noqa: BLE001  # any failure is the outcome; its message may hold credentials
        response = getattr(exc, "response", None)
        return [f"{name}: {type(exc).__name__ if response is None else response.status_code}"]
    return []
