"""Read-only: Open Formulieren's Objects API groups and active forms' registrations, checked as it uses them. Params: none.

Returns {groups: [{group, errors}], backends: [{form, backend, errors}]}. A group's errors is [] when it lists
objects and objecttypes with its own Services; a backend's errors is {} when its options validate against the live
APIs (objecttype, catalogus and types).
"""


def run(_params):
    from openforms.contrib.objects_api.clients import get_objects_client
    from openforms.contrib.objects_api.clients import get_objecttypes_client
    from openforms.contrib.objects_api.models import ObjectsAPIGroupConfig
    from openforms.forms.models import FormRegistrationBackend
    from openforms.registrations.contrib.objects_api.config import ObjectsAPIOptionsSerializer

    groups = []
    for group in ObjectsAPIGroupConfig.objects.order_by("identifier"):
        errors = [
            *_error("objects", _list_objects, get_objects_client, group),
            *_error("objecttypes", _list_objecttypes, get_objecttypes_client, group),
        ]
        groups.append({"group": group.identifier, "errors": errors})
    backends = []
    active = FormRegistrationBackend.objects.filter(backend="objects_api", form__active=True, form___is_deleted=False)
    for backend in active.select_related("form"):
        serializer = ObjectsAPIOptionsSerializer(data=backend.options, context={"validate_business_logic": True})
        backends.append({"form": backend.form.slug, "backend": backend.key, "errors": _invalid(serializer)})
    return {"groups": groups, "backends": backends}


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


def _invalid(serializer):
    if serializer.is_valid():
        return {}
    return {field: [str(error) for error in messages] for field, messages in serializer.errors.items()}
