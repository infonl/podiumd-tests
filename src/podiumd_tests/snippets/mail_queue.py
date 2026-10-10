"""The mails mentioning a text in an app's django_yubin mail queue (Open Formulieren, Open Inwoner).

Params: action, text. Actions: status (their status labels), retry (yubin's retry_emails, as the
app's beat runs it), delete.
"""


def run(params):
    from django.db.models import Q
    from django_yubin.models import Message

    mails = Message.objects.filter(Q(to_address__contains=params["text"]) | Q(_message_data__contains=params["text"]))
    if params["action"] == "status":
        return {"status": [m.get_status_display() for m in mails]}
    if params["action"] == "retry":
        from django_yubin.tasks import retry_emails

        retry_emails()
        return {"status": [m.get_status_display() for m in mails]}
    return {"removed": mails.delete()[0]}
