"""Open Archiefbeheer's zaken cache, for a test's own zaken only.

Actions: cache (fetch the zaken from Open Zaak as OAB's sync does and store them), uncache
(delete them and every destruction list that holds one). Params: action, urls. OAB's own
sync is no fit: the incremental one skips zaken that ended before the newest cached one,
the full one wipes the whole cache.
"""


def run(params):
    from openarchiefbeheer.destruction.models import DestructionList
    from openarchiefbeheer.zaken.models import Zaak

    urls = params["urls"]
    if params["action"] == "uncache":
        holding = DestructionList.objects.filter(items__zaak__url__in=urls).values("pk")
        removed = DestructionList.objects.filter(pk__in=holding).delete()[0]
        return {"removed": removed + Zaak.objects.filter(url__in=urls).delete()[0]}
    return {"cached": _cache(urls)}


def _cache(urls):
    import contextlib

    from django.core.exceptions import ImproperlyConfigured
    from djangorestframework_camel_case.parser import CamelCaseJSONParser
    from djangorestframework_camel_case.util import underscoreize
    from openarchiefbeheer.clients import selectielijst_client
    from openarchiefbeheer.clients import zrc_client
    from openarchiefbeheer.zaken.api.serializers import ZaakSerializer
    from openarchiefbeheer.zaken.utils import process_expanded_data

    try:
        selectielijst = selectielijst_client()
    except ImproperlyConfigured:
        selectielijst = contextlib.nullcontext()
    with zrc_client() as client, selectielijst as selectielijst_api:
        zaken = []
        for url in urls:
            response = client.get(
                url,
                params={"expand": "resultaat,resultaat.resultaattype,zaaktype,rollen"},
                headers={"Accept-Crs": "EPSG:4326"},
            )
            response.raise_for_status()
            # As OAB's sync (zaken.utils.pagination_helper): its serializers take snake_case.
            zaken.append(underscoreize(response.json(), **CamelCaseJSONParser.json_underscoreize))
        if selectielijst_api is not None:
            zaken = process_expanded_data(zaken, selectielijst_api)
        serializer = ZaakSerializer(data=zaken, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return len(zaken)
