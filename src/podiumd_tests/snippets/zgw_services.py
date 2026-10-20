"""Read-only: the zgw_consumers Services, each probed through its own client. Params: probes ({uuid: path}).

Returns [{uuid, name, api_root, auth_type, status}]; status is the HTTP status of GET <api_root><path>
with the Service's own credentials, the exception's type name, or None when the Service is not in probes.
"""


def run(params):
    from zgw_consumers.client import build_client
    from zgw_consumers.models import Service

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
                "status": status,
            }
        )
    return found
