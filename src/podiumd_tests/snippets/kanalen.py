"""Wiring in Open Notificaties: the kanalen the tests publish and subscribe on, with their filters.

Actions: status, apply, remove. Params: action, kanalen ({naam: [filter, ...]}),
record ({"created": [naam], "filters": {naam: [filter]}}: what an earlier apply added).
apply creates missing kanalen and adds missing filters to existing ones; remove deletes
only the kanalen and filters the record lists.
"""


def run(params):
    from django.apps import apps

    kanaal_model = apps.get_model("datamodel", "Kanaal")
    wanted = params["kanalen"]
    existing = {kanaal.naam: kanaal for kanaal in kanaal_model.objects.filter(naam__in=list(wanted))}

    if params["action"] == "status":
        kanalen_present = set(wanted) <= set(existing)
        present = kanalen_present and all(
            set(filters) <= set(existing[naam].filters) for naam, filters in wanted.items()
        )
        return {"present": present}

    record = params.get("record") or {}
    created = set(record.get("created", []))
    added = {naam: set(filters) for naam, filters in record.get("filters", {}).items()}

    if params["action"] == "remove":
        kanaal_model.objects.filter(naam__in=sorted(created)).delete()
        _remove_filters(existing, added, created)
        return {"present": False}

    for naam, filters in wanted.items():
        missing = _add(kanaal_model, existing.get(naam), naam, filters)
        if missing is None:
            created.add(naam)
        elif missing:
            added.setdefault(naam, set()).update(missing)
    added_filters = {naam: sorted(filters) for naam, filters in sorted(added.items())}
    record = {"created": sorted(created), "filters": added_filters}
    return {"present": True, "record": record}


def _remove_filters(existing, added, created):
    """Take the added filters off the kanalen that apply did not create."""
    for naam, filters in added.items():
        kanaal = existing.get(naam)
        if kanaal is not None and naam not in created:
            kanaal.filters = [kanaal_filter for kanaal_filter in kanaal.filters if kanaal_filter not in filters]
            kanaal.save()


def _add(kanaal_model, kanaal, naam, filters):
    """Create the kanaal (None), or add the filters it lacks (those filters)."""
    if kanaal is None:
        kanaal_model.objects.create(naam=naam, documentatie_link="", filters=list(filters))
        return None
    missing = [kanaal_filter for kanaal_filter in filters if kanaal_filter not in kanaal.filters]
    if missing:
        kanaal.filters = [*kanaal.filters, *missing]
        kanaal.save()
    return missing
