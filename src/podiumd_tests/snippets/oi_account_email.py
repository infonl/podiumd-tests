"""Set the e-mail address of the Open Inwoner account with a BSN. Params: bsn, email."""


def run(params):
    from open_inwoner.accounts.models import User

    return User.objects.filter(bsn=params["bsn"]).update(email=params["email"], verified_email=params["email"])
