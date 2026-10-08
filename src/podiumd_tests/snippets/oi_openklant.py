"""Wiring W6 and W8 in Open Inwoner: Open Klant 2 as klantensysteem, and the contact flow on it.

TA seed-oi-openklant2.sh and seed-oi-contactflow.sh. Actions: status, apply, remove. Params:
action, api_root, token (apply only), config (OpenKlant2Config fields: mijn_vragen_kanaal,
mijn_vragen_actor, ...), subjects (ContactFormSubject names), group (the suite's
ZGWApiGroupConfig, whose klant_backend takes a question about a zaak), record ({"service":
created pk, "config": old field values or null when created, "subjects": [created pks],
"klanten": old KlantenSysteemConfig values, "group": [pk, old klant_backend]}), which remove
restores exactly.
"""

SLUG = "ptest-bootstrap-openklant2"
KLANTEN = {"primary_backend": "openklant2", "register_contact_via_api": True}
BACKEND = "openklant2"


def run(params):
    from open_inwoner.openklant.models import KlantenSysteemConfig
    from open_inwoner.openklant.models import OpenKlant2Config
    from open_inwoner.openzaak.models import ZGWApiGroupConfig

    config = OpenKlant2Config.objects.first()
    klanten = KlantenSysteemConfig.get_solo()
    group = ZGWApiGroupConfig.objects.filter(name=params.get("group")).first()
    if params["action"] == "status":
        service = config.service if config is not None else None
        linked = service is not None and service.slug == SLUG and service.secret == params.get("token")
        backend = group is None or group.klant_backend == BACKEND
        return {"present": bool(linked and backend and all(getattr(klanten, k) == v for k, v in KLANTEN.items()))}
    record = params.get("record") or {}
    if params["action"] == "remove":
        _remove(record, config, klanten)
        return {"present": False}
    service = _service(params, record)
    if "config" not in record:
        record["config"] = _snapshot(config) if config else None
    config = config or OpenKlant2Config()
    config.service = service
    for field, value in params["config"].items():
        setattr(config, field, value)
    config.save()
    record["subjects"] = record.get("subjects", []) + _subjects(params["subjects"], config)
    if "klanten" not in record:
        record["klanten"] = {k: getattr(klanten, k) for k in KLANTEN}
    for field, value in KLANTEN.items():
        setattr(klanten, field, value)
    klanten.save()
    if group is not None:
        record.setdefault("group", [group.pk, group.klant_backend])
        group.klant_backend = BACKEND
        group.save()
    return {"present": True, "record": record}


def _service(params, record):
    from zgw_consumers.constants import APITypes
    from zgw_consumers.constants import AuthTypes
    from zgw_consumers.models import Service

    service, created = Service.objects.update_or_create(
        slug=SLUG,
        defaults={
            "label": "podiumd-tests Open Klant 2",
            "api_type": APITypes.orc,
            "api_root": params["api_root"],
            "auth_type": AuthTypes.api_key,
            "header_key": "Authorization",
            "header_value": f"Token {params['token']}",
            # Open Inwoner's Open Klant client sends this one, as "Token <secret>".
            "secret": params["token"],
        },
    )
    if created:
        record["service"] = service.pk
    return service


def _snapshot(config):
    fields = config._meta.concrete_fields  # noqa: SLF001  # Django's documented model API
    return {f.attname: getattr(config, f.attname) for f in fields if f.attname != "id"}


def _subjects(names, config):
    from open_inwoner.openklant.models import ContactFormSubject

    existing = set(ContactFormSubject.objects.filter(openklant_config=config).values_list("subject", flat=True))
    return [
        ContactFormSubject.objects.create(subject=name, openklant_config=config).pk
        for name in names
        if name not in existing
    ]


def _remove(record, config, klanten):
    from open_inwoner.openklant.models import ContactFormSubject
    from zgw_consumers.models import Service

    ContactFormSubject.objects.filter(pk__in=record.get("subjects", [])).delete()
    for field, value in (record.get("klanten") or {}).items():
        setattr(klanten, field, value)
    klanten.save()
    if config is not None and "config" in record:
        if record["config"] is None:
            config.delete()
        else:
            for field, value in record["config"].items():
                setattr(config, field, value)
            config.save()
    from open_inwoner.openzaak.models import ZGWApiGroupConfig

    if record.get("group"):
        pk, backend = record["group"]
        ZGWApiGroupConfig.objects.filter(pk=pk).update(klant_backend=backend)
    Service.objects.filter(pk=record.get("service")).delete()
