"""Open Inwoner's configuration of the test zaaktype: contact form and document upload on.

Only the suite's own zaaktype, instead of TA's zgw_import_data of every catalogus. The URLs
come from the Catalogi API of the API group (wiring W4). Actions: status, apply, remove.
Params: action, group (ZGWApiGroupConfig name), domein, rsin, identificatie, iot_omschrijving,
record ({"created": [[model, pk]], "changed": [[model, pk, {field: old value}]]}), which remove
undoes.
"""

ENABLED = {"zaaktype": {"contact_form_enabled": True}, "iot": {"document_upload_enabled": True}}


def run(params):
    from open_inwoner.openzaak.models import ZGWApiGroupConfig
    from zgw_consumers.client import build_client

    models = _models()
    record = params.get("record") or {}
    if params["action"] == "remove":
        _remove(models, record)
        return {"present": False}
    group = ZGWApiGroupConfig.objects.get(name=params["group"])
    catalogus, zaaktype, iot = _types(build_client(group.ztc_service), params)
    found = _found(models, catalogus, zaaktype, iot)
    if params["action"] == "status":
        return {"present": _present(found, zaaktype)}
    record.setdefault("created", [])
    record.setdefault("changed", [])
    if found["catalogus"] is None:
        found["catalogus"] = _create(
            models,
            record,
            "catalogus",
            url=catalogus["url"],
            domein=catalogus["domein"],
            rsin=catalogus["rsin"],
            service=group.ztc_service,
        )
    if found["zaaktype"] is None:
        found["zaaktype"] = _create(
            models,
            record,
            "zaaktype",
            catalogus=found["catalogus"],
            identificatie=zaaktype["identificatie"],
            omschrijving=zaaktype["omschrijving"],
            urls=[zaaktype["url"]],
        )
    if found["iot"] is None:
        found["iot"] = _create(
            models,
            record,
            "iot",
            zaaktype_config=found["zaaktype"],
            informatieobjecttype_url=iot["url"],
            omschrijving=iot["omschrijving"],
            zaaktype_uuids=[zaaktype["uuid"]],
        )
    _enable(record, "zaaktype", found["zaaktype"], ENABLED["zaaktype"])
    _enable(
        record,
        "iot",
        found["iot"],
        {**ENABLED["iot"], "zaaktype_uuids": sorted({*_value(found["iot"], "zaaktype_uuids"), zaaktype["uuid"]})},
    )
    return {"present": True, "record": record}


def _models():
    from open_inwoner.openzaak.models import CatalogusConfig
    from open_inwoner.openzaak.models import ZaakTypeConfig
    from open_inwoner.openzaak.models import ZaakTypeInformatieObjectTypeConfig

    return {"catalogus": CatalogusConfig, "zaaktype": ZaakTypeConfig, "iot": ZaakTypeInformatieObjectTypeConfig}


def _types(client, params):
    def first(path, **query):
        response = client.get(path, params=query)
        response.raise_for_status()
        results = response.json()["results"]
        if not results:
            msg = f"no {path} with {query} in the Catalogi API"
            raise LookupError(msg)
        return results[0]

    catalogus = first("catalogussen", domein=params["domein"], rsin=params["rsin"])
    zaaktype = first("zaaktypen", catalogus=catalogus["url"], identificatie=params["identificatie"])
    zaaktype["uuid"] = zaaktype["url"].rstrip("/").rsplit("/", 1)[-1]
    iot = first("informatieobjecttypen", catalogus=catalogus["url"], omschrijving=params["iot_omschrijving"])
    return catalogus, zaaktype, iot


def _found(models, catalogus, zaaktype, iot):
    found = {"catalogus": models["catalogus"].objects.filter(url=catalogus["url"]).first()}
    found["zaaktype"] = (
        models["zaaktype"]
        .objects.filter(catalogus__url=catalogus["url"], identificatie=zaaktype["identificatie"])
        .first()
    )
    found["iot"] = (
        models["iot"].objects.filter(zaaktype_config=found["zaaktype"], informatieobjecttype_url=iot["url"]).first()
        if found["zaaktype"]
        else None
    )
    return found


def _present(found, zaaktype):
    if found["zaaktype"] is None or found["iot"] is None:
        return False
    enabled = all(
        getattr(found[key], field) == value for key, fields in ENABLED.items() for field, value in fields.items()
    )
    return enabled and zaaktype["uuid"] in _value(found["iot"], "zaaktype_uuids")


def _create(models, record, key, **fields):
    instance = models[key].objects.create(**fields)
    record["created"].append([key, instance.pk])
    return instance


def _enable(record, key, instance, fields):
    old = {field: _value(instance, field) for field, value in fields.items() if _value(instance, field) != value}
    if not old:
        return
    if [key, instance.pk] not in record["created"]:
        record["changed"].append([key, instance.pk, old])
    for field in old:
        setattr(instance, field, fields[field])
    instance.save()


def _value(instance, field):
    # zaaktype_uuids holds UUID objects; the record and the comparisons use strings.
    value = getattr(instance, field)
    return sorted(str(uuid) for uuid in value) if field == "zaaktype_uuids" else value


def _remove(models, record):
    for key, pk, old in record.get("changed", []):
        models[key].objects.filter(pk=pk).update(**old)
    # Children before parents: the order of creation reversed.
    for key, pk in reversed(record.get("created", [])):
        models[key].objects.filter(pk=pk).delete()
