"""Read-only: every active form's Objects API registration backend, validated as Open Formulieren does. Params: none.

Returns [{form, backend, errors}]; errors is {} for a valid backend. The validation resolves the
configured objecttype, catalogus and types through the live APIs.
"""


def run(params):
    from openforms.forms.models import FormRegistrationBackend
    from openforms.registrations.contrib.objects_api.config import ObjectsAPIOptionsSerializer

    del params  # run() takes params like every snippet; this one has none
    backends = FormRegistrationBackend.objects.filter(
        backend="objects_api", form__active=True, form___is_deleted=False
    ).select_related("form")
    found = []
    for backend in backends:
        serializer = ObjectsAPIOptionsSerializer(data=backend.options, context={"validate_business_logic": True})
        errors = {} if serializer.is_valid() else {k: [str(e) for e in v] for k, v in serializer.errors.items()}
        found.append({"form": backend.form.slug, "backend": backend.key, "errors": errors})
    return found
