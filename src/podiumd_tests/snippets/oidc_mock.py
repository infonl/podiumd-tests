"""Wiring W1 in Open Inwoner or Open Formulieren: DigiD/eHerkenning login through Keycloak's mock.

Actions: status, apply, remove. Params: action, endpoint (Keycloak's openid-connect base as the
app calls it), client_id, secret (apply only), clients ({identifier: {provider, scopes, options}}),
and app extras: eherkenning_site (Open Inwoner SiteConfiguration.eherkenning_enabled), users
(Open Inwoner accounts [{bsn|kvk, email, first, last}]), form (Open Formulieren form slug that
gets the digid_oidc login), and record ({"clients": {identifier: old field values}, "providers":
[created], "created": [client identifiers created], "eherkenning_enabled": old value, "users": [created pks], "form_backend": created}),
which remove restores exactly.
"""

ENDPOINTS = {
    "oidc_op_authorization_endpoint": "auth",
    "oidc_op_token_endpoint": "token",  # nosec B105  # an endpoint path, not a password
    "oidc_op_user_endpoint": "userinfo",
    "oidc_op_jwks_endpoint": "certs",
    "oidc_op_logout_endpoint": "logout",
}


def run(params):
    from mozilla_django_oidc_db.models import OIDCClient

    clients = {c.identifier: c for c in OIDCClient.objects.filter(identifier__in=list(params["clients"]))}
    if params["action"] == "status":
        return {"present": _present(params, clients)}
    record = params.get("record") or {}
    if params["action"] == "remove":
        _remove(record, clients)
        return {"present": False}
    for key, empty in (("clients", {}), ("created", []), ("providers", []), ("users", [])):
        record.setdefault(key, empty)
    _clients(params, clients, record)
    if params.get("eherkenning_site"):
        _site(record)
    record["users"] += _users(params.get("users") or [])
    if params.get("form") and _form_backend(params["form"]):
        record["form_backend"] = params["form"]
    return {"present": True, "record": record}


def _clients(params, clients, record):
    from mozilla_django_oidc_db.models import OIDCClient
    from mozilla_django_oidc_db.models import OIDCProvider

    for identifier, wanted in params["clients"].items():
        provider, created = OIDCProvider.objects.get_or_create(identifier=wanted["provider"])
        if created:
            record["providers"].append(wanted["provider"])
        for field, path in ENDPOINTS.items():
            setattr(provider, field, f"{params['endpoint']}/{path}")
        provider.save()
        client = clients.get(identifier) or OIDCClient(identifier=identifier)
        if client.pk and identifier not in record["clients"]:
            # Every stored field except the key: what remove puts back.
            fields = client._meta.concrete_fields  # noqa: SLF001  # Django's documented model API
            record["clients"][identifier] = {f.attname: getattr(client, f.attname) for f in fields if f.attname != "id"}
        client.oidc_provider = provider
        client.oidc_rp_client_id = params["client_id"]
        client.oidc_rp_client_secret = params["secret"]
        client.oidc_rp_sign_algo = "RS256"
        client.oidc_rp_scopes_list = wanted["scopes"]
        client.options = {**(client.options or {}), **wanted["options"]}
        client.enabled = True
        if not client.pk:
            record["created"].append(identifier)
        client.save()


def _site(record):
    from open_inwoner.configurations.models import SiteConfiguration

    site = SiteConfiguration.get_solo()
    record.setdefault("eherkenning_enabled", site.eherkenning_enabled)
    site.eherkenning_enabled = True
    site.save()


def _key(user):
    return {"bsn": user["bsn"]} if "bsn" in user else {"kvk": user["kvk"]}


def _users(users):
    if not users:
        return []
    from open_inwoner.accounts.choices import LoginTypeChoices
    from open_inwoner.accounts.models import User

    created = []
    for user in users:
        if User.objects.filter(**_key(user)).exists():
            continue
        account = User.objects.create(
            **_key(user),
            email=user["email"],
            verified_email=user["email"],
            first_name=user["first"],
            last_name=user["last"],
            login_type=LoginTypeChoices.digid if "bsn" in user else LoginTypeChoices.eherkenning,
            is_active=True,
        )
        created.append(account.pk)
    return created


def _form_backend(slug):
    from openforms.forms.models import FormAuthenticationBackend

    _, created = FormAuthenticationBackend.objects.get_or_create(
        form__slug=slug, backend="digid_oidc", defaults={"form_id": _form_id(slug), "options": {}}
    )
    return created


def _form_id(slug):
    from openforms.forms.models import Form

    return Form.objects.get(slug=slug).pk


def _present(params, clients):
    from mozilla_django_oidc_db.models import OIDCProvider

    for identifier, wanted in params["clients"].items():
        client = clients.get(identifier)
        if client is None or not client.enabled or client.oidc_rp_client_id != params["client_id"]:
            return False
        provider = OIDCProvider.objects.filter(identifier=wanted["provider"]).first()
        if provider is None or provider.oidc_op_token_endpoint != f"{params['endpoint']}/token":
            return False
    if params.get("eherkenning_site"):
        from open_inwoner.configurations.models import SiteConfiguration

        if not SiteConfiguration.get_solo().eherkenning_enabled:
            return False
    if params.get("users"):
        from open_inwoner.accounts.models import User

        if not all(User.objects.filter(**_key(u)).exists() for u in params["users"]):
            return False
    if params.get("form"):
        from openforms.forms.models import FormAuthenticationBackend

        return FormAuthenticationBackend.objects.filter(form__slug=params["form"], backend="digid_oidc").exists()
    return True


def _remove(record, clients):
    from mozilla_django_oidc_db.models import OIDCProvider

    if record.get("form_backend"):
        from openforms.forms.models import FormAuthenticationBackend

        FormAuthenticationBackend.objects.filter(form__slug=record["form_backend"], backend="digid_oidc").delete()
    if record.get("users"):
        from open_inwoner.accounts.models import User

        User.objects.filter(pk__in=record["users"]).delete()
    for identifier, client in clients.items():
        if identifier in record.get("created", []):
            client.delete()
            continue
        old = record.get("clients", {}).get(identifier)
        if old is None:
            continue
        for field, value in old.items():
            setattr(client, field, value)
        client.save()
    OIDCProvider.objects.filter(identifier__in=record.get("providers", [])).delete()
    if "eherkenning_enabled" in record:
        from open_inwoner.configurations.models import SiteConfiguration

        site = SiteConfiguration.get_solo()
        site.eherkenning_enabled = record["eherkenning_enabled"]
        site.save()
