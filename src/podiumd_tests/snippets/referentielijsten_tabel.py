"""A tabel with items in Referentielijsten, whose API is read-only.

Params: action (create, delete), code; for create also naam and items, a list of {code, naam}.
Returns {"items": number of items of the tabel}.
"""


def run(params):
    import datetime

    from referentielijsten.api.models import Item
    from referentielijsten.api.models import Tabel

    if params["action"] == "delete":
        Tabel.objects.filter(code=params["code"]).delete()
        return {"items": 0}
    tabel = Tabel.objects.create(code=params["code"], naam=params["naam"])
    now = datetime.datetime.now(tz=datetime.UTC)
    for item in params["items"]:
        Item.objects.create(tabel=tabel, code=item["code"], naam=item["naam"], begindatum_geldigheid=now)
    return {"items": Item.objects.filter(tabel=tabel).count()}
