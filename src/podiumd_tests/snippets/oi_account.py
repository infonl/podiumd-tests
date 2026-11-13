"""Set fields of the Open Inwoner account with a BSN; their old values, to set back.

Params: bsn, fields ({field: value}; a date as "YYYY-MM-DD", null clears). email also sets
verified_email. With params count ({field: value}, e.g. {"kvk": ...}) instead: how many accounts match.
With params create ({"bsn": ..., "email": ...}): a new DigiD account with case notifications on.
With params delete (a BSN): delete the accounts with that BSN.
"""


def run(params):
    from open_inwoner.accounts.models import User

    if "count" in params:
        return User.objects.filter(**params["count"]).count()
    if "create" in params:
        email = params["create"]["email"]
        user = User.objects.create_user(
            email, bsn=params["create"]["bsn"], login_type="digid", verified_email=email, cases_notifications=True
        )
        return user.pk
    if "delete" in params:
        return User.objects.filter(bsn=params["delete"]).delete()[0]
    user = User.objects.get(bsn=params["bsn"])
    fields = dict(params["fields"])
    if "email" in fields:
        fields["verified_email"] = fields["email"]
    old = {field: _plain(getattr(user, field)) for field in fields}
    for field, value in fields.items():
        setattr(user, field, value)
    user.save()
    return old


def _plain(value):
    return value.isoformat() if hasattr(value, "isoformat") else value
