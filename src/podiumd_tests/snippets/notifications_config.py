"""Wiring in an app that publishes notifications (e.g. Open Klant): send them to Open Notificaties.

Only when the app has no notifications service yet: then a service on the suite's own
Open Notificaties client is linked, and the record notes it. Actions: status, apply,
remove. Params: action, prefix, notificaties_url (as the app reaches Open Notificaties),
client_id, secret, record ({"linked": true} when apply linked the service).
"""


def run(params):
    from notifications_api_common.models import NotificationsConfig
    from zgw_consumers.models import Service

    # The database row, not get_solo(): its cache can hold a stale config from another pod.
    config = NotificationsConfig.objects.first() or NotificationsConfig.get_solo()
    slug = f"{params['prefix']}-nrc"
    if params["action"] == "status":
        return {"present": config.notifications_api_service_id is not None}

    record = params.get("record") or {}
    if params["action"] == "remove":
        if record.get("linked") and config.notifications_api_service and config.notifications_api_service.slug == slug:
            config.notifications_api_service = None
            config.save()
            NotificationsConfig.clear_cache()
        Service.objects.filter(slug=slug).delete()
        return {"present": False}

    if config.notifications_api_service_id is not None and not record.get("linked"):
        # The environment owner's configuration stays; nothing to undo later.
        owner = config.notifications_api_service.slug
        return {"present": True, "record": record, "notes": [f"uses the environment's own service {owner}"]}
    Service.objects.filter(slug=slug).delete()
    service = Service.objects.create(
        slug=slug,
        label=f"{params['prefix']} Open Notificaties",
        api_type="nrc",
        api_root=params["notificaties_url"],
        auth_type="zgw",
        client_id=params["client_id"],
        secret=params["secret"],
        user_id=params["client_id"],
        user_representation=params["client_id"],
    )
    config.notifications_api_service = service
    config.save()
    NotificationsConfig.clear_cache()
    return {"present": True, "record": {"linked": True}}
