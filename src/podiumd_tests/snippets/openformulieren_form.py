"""Wiring in Open Formulieren: a test form that registers a zaak in the test catalogus.

Open Formulieren allows one service per API root, so existing services for Open Zaak's
API roots are reused (and with them the platform's own client; step
openzaak-of-autorisatie gives it rights on the test catalogus). Services are created,
on the suite's own ZGW client, only where none exists. The API group, form and
registration are test objects. Actions: status, apply (recreates), remove (test objects
only). Params: action, prefix, form_slug, openzaak_url (as Open Formulieren reaches it),
client_id, secret, domein, rsin, zaaktype, informatieobjecttype (omschrijving).
"""


def run(params):
    from openforms.forms.models import Form
    from openforms.forms.models import FormDefinition
    from openforms.forms.models import FormRegistrationBackend
    from openforms.forms.models import FormStep
    from openforms.forms.models import FormVariable
    from openforms.registrations.contrib.zgw_apis.models import ZGWApiGroupConfig
    from openforms.submissions.models import Submission
    from zgw_consumers.models import Service

    prefix = params["prefix"]
    slug = params["form_slug"]
    forms = Form.objects.filter(slug=slug)
    groups = ZGWApiGroupConfig.objects.filter(identifier=prefix)
    services = Service.objects.filter(slug__startswith=f"{prefix}-")

    if params["action"] == "status":
        # A group on another Open Zaak URL (e.g. http before the switch to https) is stale.
        current = groups.filter(zrc_service__api_root__startswith=params["openzaak_url"])
        present = current.exists() and forms.filter(active=True, registration_backends__key="zgw").exists()
        return {"present": present}

    # Submissions protect their form; those of the test form are test data.
    Submission.objects.filter(form__in=forms).delete()
    forms.delete()
    FormDefinition.objects.filter(slug=f"{slug}-step").delete()
    groups.delete()
    services.delete()
    if params["action"] == "remove":
        return {"present": False}

    created = {}
    for api_type, path in (("zrc", "zaken"), ("drc", "documenten"), ("ztc", "catalogi")):
        api_root = f"{params['openzaak_url']}/{path}/api/v1/"
        existing = Service.objects.filter(api_root=api_root).first()
        if existing is not None:
            created[api_type] = existing
            continue
        created[api_type] = Service.objects.create(
            slug=f"{prefix}-{api_type}",
            label=f"{prefix} {path}",
            api_type=api_type,
            api_root=api_root,
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
