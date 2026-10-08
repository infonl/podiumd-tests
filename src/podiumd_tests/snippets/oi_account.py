"""Set fields of the Open Inwoner account with a BSN; their old values, to set back.

Params: bsn, fields ({field: value}; a date as "YYYY-MM-DD", null clears). email also sets
verified_email.
"""


def run(params):
    from open_inwoner.accounts.models import User

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
