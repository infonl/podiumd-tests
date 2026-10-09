"""Delete the mails to an address from Open Formulieren's mail queue (django_yubin). Params: address."""


def run(params):
    from django_yubin.models import Message

    return {"removed": Message.objects.filter(to_address__contains=params["address"]).delete()[0]}
