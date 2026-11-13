"""The audittrail of an Open Zaak object: [resource, actie] per entry, oldest first.

Open Zaak 1.29.3 serves audittrails only to clients with heeft_alle_autorisaties (open-zaak-3). Params: url, the
hoofdobject (zaak, document or besluit).
"""


def run(params):
    from vng_api_common.audittrails.models import AuditTrail

    entries = AuditTrail.objects.filter(hoofd_object=params["url"]).order_by("aanmaakdatum")
    return [[entry.resource, entry.actie] for entry in entries]
