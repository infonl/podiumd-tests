# Requests for podiumd-minikube

Open requests from podiumd-tests for the agent working in infonl/podiumd-minikube.

## Keycloak: a local stand-in for the admin identity provider

podiumd-infra (kees00) and ExternalsPodiumD (dim1, dim3, dimp, info, icat and mayk ontw; dimp test) set
`keycloak.config.adminIdentityProviders`, `adminIdentityProviderMappers` and `realmIdentityProviders`:
identity provider `accp-dimp-oidc` (`keycloak-oidc`) federates logins to Dimpact's acceptance Keycloak
(`https://acc-keycloak.dimpact.nl/realms/podiumd`), and mapper `admin-mapper`
(`oidc-hardcoded-role-idp-mapper`, `syncMode: FORCE`, role `admin`) gives those users the master realm's
`admin` role. In the podiumd realm, mapper `oidc-hardcoded-group-idp-mapper` (`syncMode: FORCE`) puts them in
group `/administrators`. minikube sets none of these, so its deploys never import an identity provider or an
admin-role mapper.

That path broke kees00's deploy on 2026-10-20: Keycloak 26.8 (CVE-2026-12388) refuses the mapper with 403
unless the identity provider has `config.allowAdminRoleMapping: "true"`, and `keycloak-import-master-realm`
then fails on every run (podiumd-infra fix e0492af; helm-charts PR #623, IN-3203, adds a render check).
minikube would have shown it first.

Requested, as for the DigiD and eHerkenning mocks:

1. A realm in minikube's own Keycloak (e.g. `acc-mock`) with a client for the federation and one test user,
   standing in for the acceptance Keycloak.
2. In `keycloak.config`: `adminIdentityProviders` with an identity provider for that realm, with
   `allowAdminRoleMapping: "true"`; `adminIdentityProviderMappers` with the same `admin-mapper` as the
   estates; `realmIdentityProviders` for the podiumd realm with the group mapper to `/administrators`, as the estates
   have it.
3. Tell podiumd-tests: the identity provider alias, the realm, and the Secret name and key of the test user's
   password. podiumd-tests then adds a test: a Keycloak admin console login through that identity provider
   gets the master `admin` role.

If you leave the difference in place instead, say why in `values.yaml`, so it is a recorded choice.
