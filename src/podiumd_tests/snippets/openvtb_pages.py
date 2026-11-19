"""The HTTP status of each page of Open VTB for a temporary superuser, rendered in the pod with Django's test client.

Params: paths. The superuser logs in through the OIDC backend, which maykin 2FA lets past its second factor, as a
Keycloak login is; it is deleted afterwards.
"""


def _statuses(user, paths):
    from django.conf import settings
    from django.test import Client

    client = Client(raise_request_exception=False)
    client.force_login(user, backend=settings.MAYKIN_2FA_ALLOW_MFA_BYPASS_BACKENDS[0])
    host = settings.ALLOWED_HOSTS[0]
    return {path: client.get(path, HTTP_HOST=host, secure=True).status_code for path in paths}


def run(params):
    import uuid

    from django.contrib.auth import get_user_model

    name = f"ptest-{uuid.uuid4().hex[:8]}"
    user = get_user_model().objects.create(username=name, is_staff=True, is_superuser=True)
    try:
        statuses = _statuses(user, params["paths"])
    except Exception:
        user.delete()
        raise
    user.delete()
    return statuses
