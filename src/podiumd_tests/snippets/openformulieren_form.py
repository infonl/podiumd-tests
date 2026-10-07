"""Wiring in Open Formulieren: a test form that registers a zaak in the test catalogus.

Uses only test objects: services and an API group on the suite's own ZGW client, the
form, and its zgw-create-zaak registration. Actions: status, apply (recreates), remove.
Params: action, prefix, form_slug, openzaak_url (as Open Formulieren reaches it),
client_id, secret, domein, rsin, zaaktype, informatieobjecttype (omschrijving).
"""


def run(params):
    from openforms.forms.models import Form
    from openforms.forms.models import FormDefinition
    from openforms.forms.models import FormRegistrationBackend
    from openforms.forms.models import FormStep
    from openforms.forms.models import FormVariable
    from openforms.registrations.contrib.zgw_apis.models import ZGWApiGroupConfig
    from zgw_consumers.models import Service

    prefix = params["prefix"]
    slug = params["form_slug"]
    forms = Form.objects.filter(slug=slug)
    groups = ZGWApiGroupConfig.objects.filter(identifier=prefix)
    services = Service.objects.filter(slug__startswith=f"{prefix}-")

    if params["action"] == "status":
        present = groups.exists() and forms.filter(active=True, registration_backends__key="zgw").exists()
        return {"present": present}

    forms.delete()
    FormDefinition.objects.filter(slug=f"{slug}-step").delete()
    groups.delete()
    services.delete()
    if params["action"] == "remove":
        return {"present": False}

    created = {}
    for api_type, path in (("zrc", "zaken"), ("drc", "documenten"), ("ztc", "catalogi")):
        created[api_type] = Service.objects.create(
            slug=f"{prefix}-{api_type}",
            label=f"{prefix} {path}",
            api_type=api_type,
            api_root=f"{params['openzaak_url']}/{path}/api/v1/",
            auth_type="zgw",
            client_id=params["client_id"],
            secret=params["secret"],
            user_id=params["client_id"],
            user_representation=params["client_id"],
        )
    group = ZGWApiGroupConfig.objects.create(
        name=prefix,
        identifier=prefix,
        zrc_service=created["zrc"],
        drc_service=created["drc"],
        ztc_service=created["ztc"],
        catalogue_domain=params["domein"],
        catalogue_rsin=params["rsin"],
        organisatie_rsin=params["rsin"],
        auteur="podiumd-tests",
    )
    definition = FormDefinition.objects.create(
        slug=f"{slug}-step",
        name=f"{slug} step",
        configuration={
            "display": "form",
            "components": [
                {
                    "type": "textfield",
                    "key": "klacht_omschrijving",
                    "label": "Omschrijving",
                    "validate": {"required": True},
                }
            ],
        },
    )
    form = Form.objects.create(slug=slug, name=slug, active=True)
    FormStep.objects.create(form=form, form_definition=definition, order=0, slug="klacht")
    FormVariable.objects.create_for_form(form)
    FormRegistrationBackend.objects.create(
        form=form,
        key="zgw",
        name="ZGW zaak",
        backend="zgw-create-zaak",
        options={
            "zgw_api_group": group.pk,
            "catalogue": {"domain": params["domein"], "rsin": params["rsin"]},
            "case_type_identification": params["zaaktype"],
            "document_type_description": params["informatieobjecttype"],
            "organisatie_rsin": params["rsin"],
            "zaak_vertrouwelijkheidaanduiding": "openbaar",
        },
    )
    return {"present": True}
