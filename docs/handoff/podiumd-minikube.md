# Open requests for podiumd-minikube

## Admin login through objecttypen.local fails on podiumd 4.10.0

On Open Object, `https://objecttypen.local/oidc/authenticate/?next=/admin/` redirects to Keycloak
client `objecten` with `redirect_uri=https://objecttypen.local/oidc/callback/`. Keycloak answers
HTTP 400 because that redirect URI is not registered for the client. The same login through
objecten.local works.

Found by smoke test `tests/smoke/test_oidc.py::test_login_ends_on_the_keycloak_form[objecttypen]`
(podiumd-tests ecd6704).

Wanted: either client `objecten` also allows
`https://objecttypen.local/*`, or the objecttypen.local alias sends admin and OIDC paths to
objecten.local.
