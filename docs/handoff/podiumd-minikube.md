# Requests to podiumd-minikube

## Frank!Gateway outway with a route per app, in the api-proxy's place

podiumd-tests' smoke module `tests/smoke/test_frankgateway_apps.py` checks the end state of helm-charts'
`charts/podiumd/scripts/migrate-apiproxy-to-frankgateway.py`. That script replaces the api-proxy by the outway in
three phases, each a run with `--phase`:

1. One route per app and register (`/zac/brp/`, `/kiss/kvk/`, `/forms/bag/`, `/oip/brp/`, ...).
2. ZAC, KISS, Open Formulieren and Open Inwoner pointed at their own routes.
3. `apiproxy.enabled: false`.

The module skips until the outway has `/zac/brp/`. Requested for the frankgateway profile:

- The chart from helm-charts branch `feature/podiumd-4.10.2-frankgateway-ca-bundle` (podiumd 4.10.2,
  `upstreamTls.caBundleSecretRef`), with all three phases applied to minikube's values. The outway's upstreams are
  the minikube mocks (BRP, BAG, KvK); PDOK may stay external.
- `kiss.settings.haalCentraal.customHeaders` with an `x-request-application` that contains `kiss`: the outway sets
  that header on `forms-brp` and `oip-brp` with `forms` and `oip` in its place, and the test compares against it.
- The Secret `frankgateway-outway-admin-credentials` (key `viewer`) as the chart makes it: the profile reads it as
  `frankgateway_admin_key`.

After phase 3 the BRP, BAG and KvK component tests run through ZAC's outway routes instead of the api-proxy.

Answer in this file or by message to the podiumd-tests session.
