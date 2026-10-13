# Open requests for podiumd-minikube

## Django admin logins through keycloak-admin.local fail (since the Keycloak redeploy, de4f534)

The admins of openzaak, openformulieren and openinwoner start their OIDC login at
`https://keycloak-admin.local/realms/zaakafhandelcomponent/...`. The realm's frontendUrl
`https://keycloak.local` makes the login form post to `keycloak.local`. The browser does not
send Keycloak's login cookie, which it set on `keycloak-admin.local`, so Keycloak answers
"Restart login cookie not found" and nobody can log in to these admins.

The other Django admins start on `keycloak.local` and work.

Found by smoke test `tests/smoke/test_oidc.py::test_login_ends_on_the_keycloak_form` and
by `tests/integration/test_sso.py` (podiumd-tests 6c9aedd).

Wanted: these three admins' OIDC endpoints use `keycloak.local`, as the other admins do, or
the login stays on one host.
