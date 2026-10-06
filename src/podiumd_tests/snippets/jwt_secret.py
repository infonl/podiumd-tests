"""The shared secret of a ZGW client id (vng_api_common JWTSecret); Open Zaak, Open Notificaties."""


def run(params):
    from vng_api_common.models import JWTSecret

    return JWTSecret.objects.get(identifier=params["client_id"]).secret
