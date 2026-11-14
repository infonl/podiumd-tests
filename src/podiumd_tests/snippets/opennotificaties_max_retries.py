"""How often Open Notificaties retries a failed delivery to an abonnement (NotificationsConfig)."""


def run(_params):
    from notifications_api_common.models import NotificationsConfig

    return NotificationsConfig.get_solo().notification_delivery_max_retries
