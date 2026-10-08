"""Wiring W5 in Open Inwoner: the CMS pages the portal needs, and the contact form switched on.

TA seed-oi-cms-pages.sh. CMS 4 with djangocms-versioning: a page is published through its
Version. An apphook with an app_config (ProfileApphook) answers 404 until a config with its
namespace exists. Actions: status, apply, remove. Params: action, pages ([{slug, title, apphook,
namespace, template, home, plugin}]), contact_email (KlantenSysteemConfig.register_contact_email
when empty), record ({"pages": [created page pks], "app_configs": [[apphook, config pk]],
"contact_email": old value}), which remove undoes.
"""


def run(params):
    from cms.models import Page
    from cms.utils.apphook_reload import mark_urlconf_as_changed
    from open_inwoner.openklant.models import KlantenSysteemConfig

    existing = {p["slug"]: _find(Page, p) for p in params["pages"]}
    config = KlantenSysteemConfig.get_solo()
    missing_configs = [p for p in params["pages"] if _missing_app_config(p)]
    if params["action"] == "status":
        present = all(existing.values()) and not missing_configs and bool(config.register_contact_email)
        return {"present": present}
    record = params.get("record") or {}
    if params["action"] == "remove":
        _remove(Page, record, config)
        mark_urlconf_as_changed()
        return {"present": False}
    record.setdefault("pages", [])
    for wanted in params["pages"]:
        if existing[wanted["slug"]] is None:
            record["pages"].append(_create(wanted).pk)
    record.setdefault("app_configs", [])
    for wanted in missing_configs:
        app_config = _app_config_model(wanted).objects.create(namespace=wanted["namespace"])
        record["app_configs"].append([wanted["apphook"], app_config.pk])
    if not config.register_contact_email:
        record.setdefault("contact_email", config.register_contact_email)
        config.register_contact_email = params["contact_email"]
        config.save()
    # The running web processes load apphook URLs once; this makes them reload on their next request.
    mark_urlconf_as_changed()
    return {"present": True, "record": record}


def _find(page_model, wanted):
    if wanted.get("apphook"):
        return page_model.objects.filter(application_urls=wanted["apphook"]).first()
    return page_model.objects.filter(urls__slug=wanted["slug"]).first()


def _app_config_model(wanted):
    from cms.apphook_pool import apphook_pool

    return getattr(apphook_pool.get_apphook(wanted["apphook"]), "app_config", None) if wanted.get("apphook") else None


def _missing_app_config(wanted):
    model = _app_config_model(wanted)
    return model is not None and not model.objects.filter(namespace=wanted["namespace"]).exists()


def _create(wanted):
    from cms import api
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(is_superuser=True).first()
    kwargs = {
        "title": wanted["title"],
        "template": wanted["template"],
        "language": "nl",
        "slug": wanted["slug"],
        "in_navigation": not wanted.get("home"),
        # The side navigation needs a home page with this reverse_id.
        "reverse_id": "home" if wanted.get("home") else None,
        "created_by": user,
    }
    if wanted.get("apphook"):
        kwargs["apphook"] = wanted["apphook"]
        kwargs["apphook_namespace"] = wanted["namespace"]
    page = api.create_page(**kwargs)
    if wanted.get("plugin"):
        from cms.models import PageContent

        content = PageContent.admin_manager.filter(page=page, language="nl").latest("pk")
        api.add_plugin(content.get_placeholders().get(slot=wanted["plugin"]["slot"]), wanted["plugin"]["type"], "nl")
    _publish(page, user)
    if wanted.get("home"):
        page.set_as_homepage()
    return page


def _versions(page):
    from djangocms_versioning.models import Version

    content_pks = list(page.pagecontent_set(manager="admin_manager").values_list("pk", flat=True))
    return Version.objects.filter(object_id__in=content_pks, content_type__model="pagecontent")


def _publish(page, user):
    from djangocms_versioning.constants import DRAFT

    for version in _versions(page):
        if version.state == DRAFT:
            version.publish(user)


def _remove(page_model, record, config):
    for apphook, pk in record.get("app_configs", []):
        _app_config_model({"apphook": apphook}).objects.filter(pk=pk).delete()
    for page in page_model.objects.filter(pk__in=record.get("pages", [])):
        _versions(page).delete()
        page.delete()
    if "contact_email" in record:
        config.register_contact_email = record["contact_email"]
        config.save()
