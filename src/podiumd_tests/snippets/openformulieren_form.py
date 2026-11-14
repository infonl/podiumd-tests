"""A one-step test form in Open Formulieren with at most one registration backend.

Actions: status, apply (recreates), remove (needs only slug), list (the slugs of the forms, steps and
products whose name starts with param prefix). Params: action, slug, components (Form.io
components of the step), registration ({"backend", "options"}, or {} for none; "api_group" names the ZGW
API group whose pk goes into the options, "objects_api" is the Objecten API root of the Objects
API group whose identifier goes into the options), variables (user-defined form variables: {"key",
"data_type", "prefill_plugin", "prefill_options"}; an option of GROUPS is the API root of the group's service),
auth_backends (login plugins, e.g. digid_oidc), settings (other Form fields); apply clears Open Formulieren's catalogi lookup cache; payment (optional {"backend": ogone-legacy or worldline, "merchant":
an Ogone merchant's label or a Worldline merchant's pspid, "price"}: a product named after the form
carries the price). Submissions of the form are test data and go with it.
"""


def run(params):
    from openforms.forms.models import Form
    from openforms.forms.models import FormAuthenticationBackend
    from openforms.forms.models import FormDefinition
    from openforms.forms.models import FormStep
    from openforms.products.models import Product
    from openforms.submissions.models import Submission

    if params["action"] == "list":
        prefix = params["prefix"]
        steps = FormDefinition.objects.filter(slug__startswith=prefix, slug__endswith="-step")
        return sorted(
            set(Form.objects.filter(slug__startswith=prefix).values_list("slug", flat=True))
            | {slug.removesuffix("-step") for slug in steps.values_list("slug", flat=True)}
            | set(Product.objects.filter(name__startswith=prefix).values_list("name", flat=True))
        )

    slug = params["slug"]
    forms = Form.objects.filter(slug=slug)
    if params["action"] == "status":
        return _status(params, forms)

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
    payment_fields = _payment(params, slug)
    form = Form.objects.create(slug=slug, name=slug, active=True, **params["settings"], **payment_fields)
    FormStep.objects.create(form=form, form_definition=definition, order=0, slug="stap")
    _add_variables(form, params.get("variables", []))
    _add_registration(form, params["registration"])
    for backend in params["auth_backends"]:
        FormAuthenticationBackend.objects.create(form=form, backend=backend, options={})
    # Open Formulieren caches catalogus and zaaktype lookups for 12 hours: after a re-bootstrap it would register
    # zaken on the deleted zaaktype of the earlier bootstrap. Delete only those keys: catalogi_client proxies to the
    # default cache, which holds the sessions too, so clear() would log out every Open Formulieren user.
    from django.core.cache import caches

    caches["default"].delete_pattern("ZGW|catalogi|*")
    return {"present": True}


def _add_registration(form, registration):
    """Give the form its registration backend, if any."""
    from openforms.forms.models import FormRegistrationBackend

    if registration:
        FormRegistrationBackend.objects.create(
            form=form,
            key=registration["backend"],
            name=registration["backend"],
            backend=registration["backend"],
            options=_options(registration),
        )


def _options(registration):
    """Return the registration backend's options with the pk or identifier of the API group they name."""
    from openforms.registrations.contrib.zgw_apis.models import ZGWApiGroupConfig

    options = dict(registration["options"])
    if "api_group" in registration:
        group = ZGWApiGroupConfig.objects.filter(identifier=registration["api_group"]).first()
        options["zgw_api_group"] = group.pk if group else None
    if "objects_api" in registration:
        options["objects_api_group"] = _group("objects_api_group", registration["objects_api"])
    return options


# Option: (module, model, service field) of an API group.
GROUPS = {
    "objects_api_group": ("openforms.contrib.objects_api.models", "ObjectsAPIGroupConfig", "objects_service"),
    "customer_interactions_api_group": (
        "openforms.contrib.customer_interactions.models",
        "CustomerInteractionsAPIGroupConfig",
        "customer_interactions_service",
    ),
}


def _group(option, api_root):
    """Return the identifier of the option's API group whose service has the API root, None when there is none."""
    from importlib import import_module

    module, model, field = GROUPS[option]
    group = getattr(import_module(module), model).objects.filter(**{f"{field}__api_root": api_root}).first()
    return group.identifier if group else None


def _add_variables(form, variables):
    """Give the form the variables of its components and the user-defined variables."""
    from openforms.forms.models import FormVariable

    FormVariable.objects.create_for_form(form)
    for variable in variables:
        options = dict(variable.get("prefill_options", {}))
        for option in GROUPS.keys() & options.keys():
            options[option] = _group(option, options[option])
        FormVariable.objects.create(
            form=form,
            source="user_defined",
            key=variable["key"],
            name=variable["key"],
            data_type=variable["data_type"],
            prefill_plugin=variable.get("prefill_plugin", ""),
            prefill_options=options,
        )


def _status(params, forms):
    from openforms.forms.models import FormAuthenticationBackend
    from openforms.forms.models import FormDefinition
    from openforms.forms.models import FormRegistrationBackend

    slug = params["slug"]
    registration = params["registration"]
    backends = FormRegistrationBackend.objects.filter(form__in=forms.filter(active=True))
    logins = FormAuthenticationBackend.objects.filter(form__in=forms, backend__in=params["auth_backends"])
    definition = FormDefinition.objects.filter(slug=f"{slug}-step").first()
    # A recreated API group has a new pk; options holding the old one are stale.
    present = backends.filter(backend=registration["backend"], options=_options(registration)).exists()
    current = definition is not None and definition.configuration.get("components") == params["components"]
    return {"present": present and current and logins.count() == len(params["auth_backends"])}


def _payment(params, slug):
    """Return the Form fields of a form that asks for a payment."""
    from openforms.products.models import Product

    payment = params.get("payment")
    if not payment:
        return {}
    if payment["backend"] == "ogone-legacy":
        # Open Formulieren 4.0 removed the Ogone plugin: import it only for an Ogone form.
        from openforms.payments.contrib.ogone.models import OgoneMerchant

        options = {"merchant_id": OgoneMerchant.objects.get(label=payment["merchant"]).pk}
    else:
        options = {"merchant": payment["merchant"], "variant": "", "descriptor_template": ""}
    return {
        "product": Product.objects.create(name=slug[:50], price=payment["price"]),
        "payment_backend": payment["backend"],
        "payment_backend_options": options,
    }
