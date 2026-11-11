"""Bootstrap step: a DRF API token for Open VTB, tied to a dedicated user.

Open VTB authenticates its API with rest_framework.authtoken (a Token per user), not a vng TokenAuth,
so this is separate from snippets/token_auth.py. Actions: status, apply (replaces the token), remove.
Params: action, username, secret (apply only).
"""


def run(params):
    from django.contrib.auth import get_user_model
    from rest_framework.authtoken.models import Token

    user_model = get_user_model()
    username = params["username"]
    if params["action"] == "status":
        return {"present": Token.objects.filter(user__username=username).exists()}
    if params["action"] == "remove":
        return {"removed": user_model.objects.filter(username=username).delete()[0]}
    user, _ = user_model.objects.get_or_create(username=username, defaults={"email": "podiumd-tests@example.invalid"})
    Token.objects.filter(user=user).delete()
    Token.objects.create(user=user, key=params["secret"])
    return {"present": True}
