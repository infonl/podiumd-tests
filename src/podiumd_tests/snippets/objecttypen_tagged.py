"""Run-tagged objecttypes in Objecttypen: list or delete them, published versions too.

The API refuses to delete a published version, and an objecttype that has versions.
Actions: list (params prefix: names starting with it), delete (params name; its versions go with it).
"""

# include: _objecttypes


def run(params):
    object_type_model, _ = objecttype_models()

    if params["action"] == "list":
        found = object_type_model.objects.filter(name__startswith=params["prefix"])
        return sorted(set(found.values_list("name", flat=True)))
    object_type_model.objects.filter(name=params["name"]).delete()
    return {"deleted": params["name"]}
