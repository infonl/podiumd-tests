"""Bootstrap step: a local Django user with groups, e.g. an Open Archiefbeheer role user.

Actions: status, apply (recreates), remove. Params: action, username, email, groups, staff,
fields (other user fields), api_token, totp, secret (the password; with api_token the user's API token
instead, and no password; apply only). totp: a confirmed TOTP device whose key is the SHA-1 of the password, for
admins that require two-factor login. Groups the app lacks are left
out and reported. A user model without username (Open Inwoner) logs in with the email.
sso_users (each with username and email): users the app made itself when a Keycloak test user logged in
through OIDC; apply and remove delete them, so no test user stays behind after an unbootstrap.
"""


def run(params):
    from importlib.util import find_spec

    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    model = get_user_model()
    login = params["email"] if model.USERNAME_FIELD == "email" else params["username"]
    users = model.objects.filter(**{model.USERNAME_FIELD: login})
    if params["action"] == "status":
        return {"present": users.filter(is_active=True).exists()}
    users.delete()
    sso_field = "email" if model.USERNAME_FIELD == "email" else "username"
    sso_logins = [sso_user[sso_field] for sso_user in params.get("sso_users", [])]
    model.objects.filter(**{f"{model.USERNAME_FIELD}__in": sso_logins}).delete()
    if params["action"] == "remove":
        return {"present": False}
    fields = {"email": params["email"], "password": params["secret"], "is_staff": params["staff"], **params["fields"]}
    if model.USERNAME_FIELD != "email":
        fields["username"] = params["username"]
    user = model.objects.create_user(**fields)
    if params["api_token"]:
        from rest_framework.authtoken.models import Token

        user.set_unusable_password()
        user.save()
        Token.objects.create(user=user, key=params["secret"])
    if params["totp"] and find_spec("django_otp") is not None:
        import hashlib

        from django_otp.plugins.otp_totp.models import TOTPDevice

        key = hashlib.sha1(params["secret"].encode(), usedforsecurity=False).hexdigest()
        # two_factor logs in with the device named "default" only.
        TOTPDevice.objects.create(user=user, name="default", key=key, confirmed=True)
    groups = list(Group.objects.filter(name__in=params["groups"]))
    user.groups.set(groups)
    if find_spec("axes") is not None:
        from axes.utils import reset

        reset(username=login)  # clear login lockouts of an earlier user with this name
    found = {group.name for group in groups}
    missing = [group for group in params["groups"] if group not in found]
    return {"present": True, "notes": [f"no group {group}" for group in missing]}
