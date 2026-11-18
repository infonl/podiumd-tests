"""Bootstrap step: the Open Inwoner accounts that the DigiD and eHerkenning mock logins of the test identities make.

Nothing to create: Open Inwoner makes an account at a test identity's first login, with the identity's e-mail
address (ptest-bootstrap-<name>@example.invalid). Remove deletes those DigiD and eHerkenning accounts, so no
test account stays behind after an unbootstrap. Accounts with the same BSN or KvK number but another e-mail
address are not ours and stay. Params: action.
"""


def run(params):
    from open_inwoner.accounts.models import User

    if params["action"] == "remove":
        accounts = User.objects.filter(email__startswith="ptest-bootstrap-", email__endswith="@example.invalid")
        accounts.filter(login_type__in=["digid", "eherkenning"]).delete()
    return {"present": True}
