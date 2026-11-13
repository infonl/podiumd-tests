"""The outcome of Open Inwoner's latest received notification about a resource: status and processing output.

Params: resource_url. Returns null when Open Inwoner received none.
"""


def run(params):
    from notifications.models import NotificationRecord

    found = NotificationRecord.objects.filter(payload__resourceUrl=params["resource_url"]).order_by("-received_at")
    record = found.first()
    if record is None:
        return None
    return {"status": record.status, "output": record.processing_output, "error": record.processing_error}
