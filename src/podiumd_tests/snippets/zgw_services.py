"""Read-only: the zgw_consumers Services, each probed through its own client. Params: probes ({uuid: path}), used.

used is a list of Service filters for Services an app uses by type, without a field (Open Beheer's Catalogi APIs).
Returns [{uuid, name, api_root, auth_type, referenced, status}]; referenced is True when a config field (any
foreign key or many-to-many to Service) or a filter in used selects it; status is the HTTP status of
GET <api_root><path> with the Service's own credentials, the exception's type name, or None when the Service is
not in probes.
"""


def run(params):
    from zgw_consumers.models import Service

    referenced = _referenced(params)
    found = []
    for service in Service.objects.order_by("slug", "api_root"):
        uuid = str(service.uuid)
        status = _probe(service, params["probes"][uuid]) if uuid in params["probes"] else None
        found.append(
            {
                "uuid": uuid,
                "name": service.slug or service.label,
                "api_root": service.api_root,
                "auth_type": service.auth_type,
                "referenced": service.pk in referenced,
                "status": status,
            }
        )
    return found


def _referenced(params):
    """Return the pks of the Services a model field refers to, and of those params["used"] selects."""
    from django.apps import apps
    from zgw_consumers.models import Service

    referenced = set()
    for model in apps.get_models():
        for field in _service_fields(model, Service):
            rows = model._default_manager.exclude(**{f"{field.name}__isnull": True})
            referenced |= set(rows.values_list(f"{field.name}__pk", flat=True))
    for where in params.get("used", []):
        referenced |= set(Service.objects.filter(**where).values_list("pk", flat=True))
    return referenced


def _service_fields(model, service_model):
    fields = model._meta.get_fields()
    return [field for field in fields if field.concrete and getattr(field, "related_model", None) is service_model]


def _probe(service, path):
    """Return the status of a GET of path through the Service's own client, or the name of the error."""
    from zgw_consumers.client import build_client

    try:
        with build_client(service) as client:
            response = client.get(path, timeout=10)
    except Exception as exc:  # noqa: BLE001  # any failure is the outcome; its message may hold credentials
        return type(exc).__name__
    return response.status_code
