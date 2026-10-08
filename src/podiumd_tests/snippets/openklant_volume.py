"""Volume data in Open Klant (seed-volume): count or delete one kind. Params: action (count, delete), kind, tag.

Kind partijen: partijen whose interne_notitie starts with the tag. Kind internetaken: internetaken
whose toelichting starts with it, with the klantcontacten (onderwerp) and actoren (naam) of the
volume. Returns {"count": ...}, after deleting for delete.
"""


def run(params):
    from django.db import transaction
    from openklant.components.klantinteracties.models.actoren import Actor
    from openklant.components.klantinteracties.models.internetaken import InterneTaak
    from openklant.components.klantinteracties.models.klantcontacten import Klantcontact
    from openklant.components.klantinteracties.models.partijen import Partij

    tag = params["tag"]
    if params["kind"] == "partijen":
        queries = [Partij.objects.filter(interne_notitie__startswith=tag)]
    else:
        # In order: internetaken refer to klantcontacten and actoren.
        queries = [
            InterneTaak.objects.filter(toelichting__startswith=tag),
            Klantcontact.objects.filter(onderwerp__startswith=tag),
            Actor.objects.filter(naam__startswith=tag),
        ]
    if params["action"] == "delete":
        with transaction.atomic():
            for query in queries:
                query.delete()
    return {"count": queries[0].count()}
