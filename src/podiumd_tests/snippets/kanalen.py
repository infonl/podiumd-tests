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
    existing = {k.naam: k for k in kanaal_model.objects.filter(naam__in=list(wanted))}

    if params["action"] == "status":
        present = all(n in existing and set(f) <= set(existing[n].filters) for n, f in wanted.items())
        return {"present": present}

    record = params.get("record") or {}
    created = set(record.get("created", []))
    added = {naam: set(filters) for naam, filters in record.get("filters", {}).items()}

    if params["action"] == "remove":
        kanaal_model.objects.filter(naam__in=sorted(created)).delete()
        for naam, filters in added.items():
            kanaal = existing.get(naam)
            if kanaal is not None and naam not in created:
                kanaal.filters = [f for f in kanaal.filters if f not in filters]
                kanaal.save()
        return {"present": False}

    for naam, filters in wanted.items():
        kanaal = existing.get(naam)
        if kanaal is None:
            kanaal_model.objects.create(naam=naam, documentatie_link="", filters=list(filters))
            created.add(naam)
            continue
        missing = [f for f in filters if f not in kanaal.filters]
        if missing:
            kanaal.filters = [*kanaal.filters, *missing]
            kanaal.save()
            added.setdefault(naam, set()).update(missing)
    record = {"created": sorted(created), "filters": {n: sorted(f) for n, f in sorted(added.items())}}
    return {"present": True, "record": record}
