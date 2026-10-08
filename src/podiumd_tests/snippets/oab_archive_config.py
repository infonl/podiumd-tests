"""Open Archiefbeheer's global ArchiveConfig: set fields, return their old values to restore later.

The destruction report goes to a zaak of config.zaaktype; zaaktypes in zaaktypes_short_process
skip the archivist. Params: fields ({field: value}). Returns the old values of those fields.
"""


def run(params):
    from openarchiefbeheer.config.models import ArchiveConfig

    config = ArchiveConfig.get_solo()
    old = {field: getattr(config, field) for field in params["fields"]}
    for field, value in params["fields"].items():
        setattr(config, field, value)
    config.save()
    return old
