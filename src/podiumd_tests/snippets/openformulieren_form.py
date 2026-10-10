"""A one-step test form in Open Formulieren with one registration backend.

Actions: status, apply (recreates), remove. Params: action, slug, components (Form.io
components of the step), registration ({"backend", "options"}; "api_group" names the ZGW
API group whose pk goes into the options, "objects_api" is the Objecten API root of the Objects
API group whose identifier goes into the options), auth_backends (login plugins, e.g. digid_oidc),
settings (other Form fields), payment (optional {"backend", "merchant": label of an Ogone merchant,
"price"}: a product named after the form carries the price). Submissions of the form are test
data and go with it.
"""


def run(params):
    from openforms.forms.models import Form
    from openforms.forms.models import FormAuthenticationBackend
    from openforms.forms.models import FormDefinition
    from openforms.forms.models import FormRegistrationBackend
    from openforms.forms.models import FormStep
    from openforms.forms.models import FormVariable
    from openforms.products.models import Product
    from openforms.registrations.contrib.zgw_apis.models import ZGWApiGroupConfig
    from openforms.submissions.models import Submission

    slug = params["slug"]
    registration = params["registration"]
    options = dict(registration["options"])
    if "api_group" in registration:
        group = ZGWApiGroupConfig.objects.filter(identifier=registration["api_group"]).first()
        options["zgw_api_group"] = group.pk if group else None
    if "objects_api" in registration:
        from openforms.contrib.objects_api.models import ObjectsAPIGroupConfig

        objects = ObjectsAPIGroupConfig.objects.filter(objects_service__api_root=registration["objects_api"]).first()
        options["objects_api_group"] = objects.identifier if objects else None
    forms = Form.objects.filter(slug=slug)

    if params["action"] == "status":
        backends = FormRegistrationBackend.objects.filter(form__in=forms.filter(active=True))
        logins = FormAuthenticationBackend.objects.filter(form__in=forms, backend__in=params["auth_backends"])
        definition = FormDefinition.objects.filter(slug=f"{slug}-step").first()
        # A recreated API group has a new pk; options holding the old one are stale.
        present = backends.filter(backend=registration["backend"], options=options).exists()
        current = definition is not None and definition.configuration.get("components") == params["components"]
        return {"present": present and current and logins.count() == len(params["auth_backends"])}

    # Submissions protect their form.
    Submission.objects.filter(form__in=forms).delete()
    forms.delete()
    FormDefinition.objects.filter(slug=f"{slug}-step").delete()
    Product.objects.filter(name=slug[:50]).delete()
    if params["action"] == "remove":
        return {"present": False}

    definition = FormDefinition.objects.create(
        slug=f"{slug}-step",
        name=f"{slug} step",
        configuration={"display": "form", "components": params["components"]},
    )
    form = Form.objects.create(slug=slug, name=slug, active=True, **params["settings"], **_payment(params, slug))
    FormStep.objects.create(form=form, form_definition=definition, order=0, slug="stap")
    FormVariable.objects.create_for_form(form)
    FormRegistrationBackend.objects.create(
        form=form,
        key=registration["backend"],
        name=registration["backend"],
        backend=registration["backend"],
        options=options,
    )
    for backend in params["auth_backends"]:
        FormAuthenticationBackend.objects.create(form=form, backend=backend, options={})
    return {"present": True}


def _payment(params, slug):
    """The Form fields of a form that asks for a payment."""
    from openforms.payments.contrib.ogone.models import OgoneMerchant
    from openforms.products.models import Product

    payment = params.get("payment")
    if not payment:
        return {}
    merchant = OgoneMerchant.objects.get(label=payment["merchant"])
    return {
        "product": Product.objects.create(name=slug[:50], price=payment["price"]),
        "payment_backend": payment["backend"],
        "payment_backend_options": {"merchant_id": merchant.pk},
    }
