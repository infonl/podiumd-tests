"""A global config of Open Archiefbeheer: set fields, return their old values to restore later.

ArchiveConfig: the destruction report goes to a zaak of zaaktype; zaaktypes in zaaktypes_short_process skip the
archivist. EmailConfig: the subject and bodies of each mail; OAB sends none whose subject or a body is empty.
Params: model (ArchiveConfig, EmailConfig), fields ({field: value}). Returns the old values of those fields.
"""


def run(params):
    from openarchiefbeheer.config.models import ArchiveConfig
    from openarchiefbeheer.emails.models import EmailConfig

    config = {"ArchiveConfig": ArchiveConfig, "EmailConfig": EmailConfig}[params["model"]].get_solo()
    old = {field: getattr(config, field) for field in params["fields"]}
    for field, value in params["fields"].items():
        setattr(config, field, value)
    config.save()
    return old
