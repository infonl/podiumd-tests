# Requests to podiumd-minikube

## Edge WAF: TLS 1.2 cipher suites per the NCSC guidelines

Every public host on minikube agrees over TLS 1.2 to 16 suites outside the NCSC TLS guidelines (2.1), which the Common
Ground ADR validator's security-tls ruleset checks:

- static RSA without forward secrecy: AES256-GCM-SHA384, AES128-GCM-SHA256, AES256-CCM, AES128-CCM, AES256-SHA256,
  AES128-SHA256, AES256-SHA, AES128-SHA, CAMELLIA256-SHA256, CAMELLIA128-SHA256, CAMELLIA256-SHA, CAMELLIA128-SHA;
- ARIA: ECDHE-ARIA256-GCM-SHA384, ECDHE-ARIA128-GCM-SHA256, ARIA256-GCM-SHA384, ARIA128-GCM-SHA256.

TLS ends at the WAF in `ingress-basic` (owasp/modsecurity-crs nginx): `nginx -T` shows `ssl_protocols TLSv1.2 TLSv1.3;`
and no `ssl_ciphers`, so nginx uses its default `HIGH:!aNULL:!MD5`. TLS 1.0 and 1.1 are refused (good).

Request: in `src/podiumd_minikube/waf.py` (around line 158) set `ssl_ciphers` to the NCSC "good" and "sufficient"
TLS 1.2 suites (ECDHE with AES-GCM or CHACHA20-POLY1305, and DHE with AES-GCM if you keep DHE) and
`ssl_prefer_server_ciphers on;`. podiumd-infra's WAF has the same gap; it is asked the same.

podiumd-tests' `test_tls_meets_ncsc_guidelines` (tests/smoke/test_web_security.py) checks it; it is merged once the
edges pass. Answer or tell the podiumd-tests session when it is deployed.
