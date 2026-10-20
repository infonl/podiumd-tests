"""Read-only: the Services that config fields reference. Params: references ([{model, field, where}]).

Returns, per reference, one entry per row of model (filtered by where): the referenced Service's
name, or None when the field is unset. An empty field means the rows are Services themselves.
"""


def run(params):
    from django.apps import apps

    found = []
    for reference in params["references"]:
        rows = apps.get_model(reference["model"])._default_manager.filter(**reference["where"])
        services = [getattr(row, reference["field"]) if reference["field"] else row for row in rows]
        found.append([s.slug or s.label if s else None for s in services])
    return found
