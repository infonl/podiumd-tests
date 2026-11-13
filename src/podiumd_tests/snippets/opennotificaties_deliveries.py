"""The HTTP statuses of Open Notificaties' deliveries of the notification about a resource, oldest first.

Params: resource_url, callback_suffix (the end of the abonnement's callback URL). Open Notificaties logs deliveries
only with LOG_NOTIFICATIONS_IN_DB; a failed connection has status null.
"""


def run(params):
    from django.apps import apps

    deliveries = apps.get_model("datamodel", "NotificatieResponse").objects.filter(
        notificatie__forwarded_msg__resourceUrl=params["resource_url"],
        abonnement__callback_url__endswith=params["callback_suffix"],
    )
    return [delivery.response_status for delivery in deliveries.order_by("id")]
