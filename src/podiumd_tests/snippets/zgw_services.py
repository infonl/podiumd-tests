"""Read-only: the zgw_consumers Services, each probed through its own client. Params: probes ({uuid: path}), used.

used is a list of Service filters for Services an app uses by type, without a field (Open Beheer's Catalogi APIs).
Returns [{uuid, name, api_root, auth_type, referenced, status}]; referenced is True when a config field (any
foreign key or many-to-many to Service) or a filter in used selects it; status is the HTTP status of
GET <api_root><path> with the Service's own credentials, the exception's type name, or None when the Service is
not in probes.
"""


def run(params):
    from django.apps import apps
    from zgw_consumers.client import build_client
    from zgw_consumers.models import Service

    referenced = set()
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if not field.concrete or getattr(field, "related_model", None) is not Service:
                continue
            rows = model._default_manager.exclude(**{f"{field.name}__isnull": True})
            referenced |= set(rows.values_list(f"{field.name}__pk", flat=True))
    for where in params.get("used", []):
        referenced |= set(Service.objects.filter(**where).values_list("pk", flat=True))
    found = []
    for service in Service.objects.order_by("slug", "api_root"):
        uuid = str(service.uuid)
        status = None
        if uuid in params["probes"]:
            try:
                with build_client(service) as client:
                    status = client.get(params["probes"][uuid], timeout=10).status_code
            except Exception as exc:  # noqa: BLE001  # any failure is the outcome; its message may hold credentials
                status = type(exc).__name__
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
