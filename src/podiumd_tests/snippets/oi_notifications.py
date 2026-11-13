"""Open Inwoner's webhook subscription, which accepts Open Notificaties' calls signed with its secret.

Its NotificationsAPIConfig uses the Notificaties API service with root nrc_url; apply creates that config only
when none exists. Actions: status, apply, remove; wired: whether any Subscription, the suite's or not, is on kanaal
zaken. Params: action, client_id, secret, callback_url, nrc_url, record ({"config": pk created by apply or null}).
"""


def run(params):
    from notifications.models import NotificationsAPIConfig
    from notifications.models import Subscription

    if params["action"] == "wired":
        return {"present": Subscription.objects.filter(channels__contains=["zaken"]).exists()}
    subscriptions = Subscription.objects.filter(client_id=params["client_id"])
    if params["action"] == "status":
        return {"present": subscriptions.exists()}
    record = params.get("record") or {}
    # Remove first, also for apply: a Subscription PROTECTs its config.
    subscriptions.delete()
    NotificationsAPIConfig.objects.filter(pk=record.get("config"), subscription__isnull=True).delete()
    if params["action"] == "remove":
        return {"present": False}
    config, created = _config(params["nrc_url"])
    Subscription.objects.create(
        notifications_api_config=config,
        callback_url=params["callback_url"],
        client_id=params["client_id"],
        secret=params["secret"],
        channels=["zaken"],
    )
    return {"present": True, "record": {"config": config.pk if created else None}}


def _config(nrc_url):
    from notifications.models import NotificationsAPIConfig
    from zgw_consumers.models import Service

    service = Service.objects.filter(api_root=nrc_url).first()
    if service is None:
        msg = f"Open Inwoner has no Notificaties API service {nrc_url}: the environment owner configures it"
        raise LookupError(msg)
    found = NotificationsAPIConfig.objects.filter(notifications_api_service=service).first()
    if found:
        return found, False
    return NotificationsAPIConfig.objects.create(notifications_api_service=service), True
