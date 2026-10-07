"""Bootstrap step: a local Django user with groups, e.g. an Open Archiefbeheer role user.

Actions: status, apply (recreates), remove. Params: action, username, email, groups, secret
(the password; apply only). Groups the app lacks are left out and reported.
"""


def run(params):
    import importlib.util

    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    users = get_user_model().objects.filter(username=params["username"])
    if params["action"] == "status":
        return {"present": users.filter(is_active=True).exists()}
    users.delete()
    if params["action"] == "remove":
        return {"present": False}
    user = get_user_model().objects.create_user(
        username=params["username"],
        email=params["email"],
        password=params["secret"],
        is_staff=True,
    )
    groups = list(Group.objects.filter(name__in=params["groups"]))
    user.groups.set(groups)
    if importlib.util.find_spec("axes") is not None:
        from axes.utils import reset

        reset(username=params["username"])  # clear login lockouts of an earlier user with this name
    found = {g.name for g in groups}
    missing = [g for g in params["groups"] if g not in found]
    return {"present": True, "notes": [f"no group {g}" for g in missing]}
