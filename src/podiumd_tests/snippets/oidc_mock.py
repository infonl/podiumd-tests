"""Wiring W1 in Open Inwoner or Open Formulieren: DigiD/eHerkenning login through Keycloak's mock.

Actions: status, apply, remove. Params: action, endpoint (Keycloak's openid-connect base as the
app calls it), client_id, secret (apply only), clients ({identifier: {provider, scopes, options}}),
and app extras: eherkenning_site (Open Inwoner SiteConfiguration.eherkenning_enabled), identities
(the test identities' numbers [{bsn} or {kvk}]), accounts (Open Inwoner accounts to prepare
[{bsn, email, first, last}]), form (Open Formulieren form slug) with form_backends (the logins
it gets, e.g. digid_oidc), and record ({"clients": {identifier: old field values}, "providers":
[created], "created": [client identifiers created], "eherkenning_enabled": old value, "accounts_before":
[pks of the identities' accounts that existed before], "form_backends": [created]}), which remove
restores exactly. remove deletes every account of the identities except those that existed before: also
the ones Open Inwoner creates itself at a login.
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
        if params.get("identities") and "accounts_before" in record:
            _delete_accounts(_accounts(params["identities"]).exclude(pk__in=record["accounts_before"]))
        return {"present": False}
    for key, empty in (("clients", {}), ("created", []), ("providers", [])):
        record.setdefault(key, empty)
    _clients(params, clients, record)
    if params.get("eherkenning_site"):
        _site(record)
    if params.get("identities"):
        record.setdefault("accounts_before", list(_accounts(params["identities"]).values_list("pk", flat=True)))
        _create_accounts(params.get("accounts") or [])
    if params.get("form"):
        created = [b for b in params["form_backends"] if _form_backend(params["form"], b)]
        record["form"] = params["form"]
        record["form_backends"] = [*record.get("form_backends", []), *created]
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


def _accounts(identities):
    """The Open Inwoner accounts with the identities' bsn or kvk."""
    from django.db.models import Q
    from open_inwoner.accounts.models import User

    query = Q(pk__in=[])
    for identity in identities:
        query |= Q(**identity)
    return User.objects.filter(query)


def _delete_accounts(accounts):
    # Rendering a page for a logged-in account creates CMS static alias Versions with
    # created_by that account, a protected foreign key: hand them over to a superuser.
    from django.contrib.auth import get_user_model
    from djangocms_versioning.models import Version

    superuser = get_user_model().objects.filter(is_superuser=True).first()
    Version.objects.filter(created_by__in=accounts).update(created_by=superuser)
    accounts.delete()


def _create_accounts(accounts):
    from open_inwoner.accounts.choices import LoginTypeChoices
    from open_inwoner.accounts.models import User

    for user in accounts:
        if User.objects.filter(bsn=user["bsn"]).exists():
            continue
        User.objects.create(
            bsn=user["bsn"],
            email=user["email"],
            verified_email=user["email"],
            first_name=user["first"],
            last_name=user["last"],
            login_type=LoginTypeChoices.digid,
            is_active=True,
        )


def _form_backend(slug, backend):
    from openforms.forms.models import FormAuthenticationBackend

    _, created = FormAuthenticationBackend.objects.get_or_create(
        form__slug=slug, backend=backend, defaults={"form_id": _form_id(slug), "options": {}}
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
    if params.get("accounts"):
        from open_inwoner.accounts.models import User

        if not all(User.objects.filter(bsn=u["bsn"]).exists() for u in params["accounts"]):
            return False
    if params.get("form"):
        from openforms.forms.models import FormAuthenticationBackend

        found = FormAuthenticationBackend.objects.filter(form__slug=params["form"], backend__in=params["form_backends"])
        return found.count() == len(params["form_backends"])
    return True


def _remove(record, clients):
    from mozilla_django_oidc_db.models import OIDCProvider

    if record.get("form_backends"):
        from openforms.forms.models import FormAuthenticationBackend

        FormAuthenticationBackend.objects.filter(
            form__slug=record["form"], backend__in=record["form_backends"]
        ).delete()
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
