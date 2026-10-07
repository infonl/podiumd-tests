"""Send one e-mail with the app's own mail settings. Params: subject, to. Returns the sender address."""


def run(params):
    from django.conf import settings
    from django.core.mail import send_mail

    send_mail(params["subject"], "podiumd-tests", None, [params["to"]])
    return {"from": settings.DEFAULT_FROM_EMAIL}
