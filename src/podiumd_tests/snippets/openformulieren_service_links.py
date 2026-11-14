"""Open Formulieren's config fields that name a service: BRP Personen, KvK basisprofiel, BAG address lookup.

Params: links ({config field: zgw_consumers Service slug}). Record mode: apply links each field and
records its old service id; remove puts that back where the field still holds the linked service.
"""

CONFIGS = {
    "brp_personen_service": ("openforms.contrib.haal_centraal.models", "HaalCentraalConfig"),
    "profile_service": ("openforms.contrib.kvk.models", "KVKConfig"),
    "bag_service": ("openforms.contrib.kadaster.models", "KadasterApiConfig"),
}


def run(params):
    record = params.get("record") or {}
    linked, notes = [], []
    for field, slug in params["links"].items():
        is_linked, note = _link(params["action"], field, slug, record)
        linked.append(is_linked)
        notes.extend(note)
    if params["action"] == "status":
        return {"present": all(linked)}
    return {"present": params["action"] == "apply", "record": record, "notes": notes}


def _link(action, field, slug, record):
    """Link (apply) or unlink (remove) one field; whether it held the service before, and a note if none exists."""
    from importlib import import_module

    from zgw_consumers.models import Service

    module, model = CONFIGS[field]
    config = getattr(import_module(module), model).get_solo()
    service = Service.objects.filter(slug=slug).first()
    if service is None:
        return False, [f"no zgw_consumers Service {slug}: {model}.{field} stays unlinked"]
    current = getattr(config, f"{field}_id")
    is_linked = current == service.pk
    if action == "apply" and not is_linked:
        record.setdefault(field, current)
        setattr(config, field, service)
        config.save()
    elif action == "remove" and field in record and is_linked:
        setattr(config, f"{field}_id", record[field])
        config.save()
    return is_linked, []
