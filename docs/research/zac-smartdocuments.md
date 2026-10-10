# ZAC and SmartDocuments

Analysed 2026-10-10, read-only, from ZAC's source at tag `v5.4.5` (paths under `src/main/kotlin/nl/info/`) and
the podiumd chart. For draaiboek ZAC-035, ZAC-036, INT-010 and CONT-045, which are out of scope for now
(`MIGRATION.md`, section Draaiboek).

## Why there is no test

- SmartDocuments is off in ZAC on every estate: `zac.smartDocuments.enabled: false` without a URL in all
  ExternalsPodiumD and podiumd-infra environments, and on minikube.
- ZAC reads the SmartDocuments URL and token from its Deployment's environment. Pointing ZAC at a mock changes the
  environment owner's deployment, unlike Open Formulieren's payment merchants, which are runtime data.
- A mock can start from ZAC's own WireMock stubs, `scripts/docker-compose/imports/smartdocuments-wiremock/` in
  ZAC's repository (minikube removed its unused copy on 2026-10-10).
- On an estate with the real SmartDocuments, a test can check the connection and the start of a document. The
  document only exists after a user fills in SmartDocuments' own wizard.

## Configuration (`zac/smartdocuments/SmartDocumentsService.kt`)

| Environment variable | Meaning |
|---|---|
| `SMARTDOCUMENTS_ENABLED` | default false |
| `SMARTDOCUMENTS_CLIENT_MP_REST_URL` | base URL; http and a path prefix work; required when enabled |
| `SMARTDOCUMENTS_AUTHENTICATION` | sent as `Authorization: Basic <value>`, the raw value; required when enabled |
| `SMARTDOCUMENTS_FIXED_USER_NAME` | replaces the user's id in the `Username` header |
| `SMARTDOCUMENTS_WIZARD_AUTH_ENABLED` | default true; false calls `wizard_no_auth` without `Username` |

The ZAC chart (`smartDocuments.enabled`, `url`, `authentication`, `fixedUserName`, `wizardAuthEnabled`) sets
`SMARTDOCUMENTS_WIZARD_AUTH_ENABLED` only when the value is true, so false cannot take effect through the chart.

## Calls ZAC makes (`client/smartdocuments/SmartDocumentsClient.kt`)

1. `GET {base}/sdapi/structure` with `Authorization` and `Username`: the template groups and templates
   (`documentsStructure.templatesStructure.templateGroups[].{id, name, templates[].{id, name}, templateGroups}`;
   the other fields of the model must be present).
2. `POST {base}/wsxmldeposit/deposit/wizard` with `Authorization` and `Username`: body
   `{"SmartDocument": {"Selection": {"TemplateGroup", "Template", "FixedValues": ""}, "Variables":
   {"OutputFormats": [{"OutputFormat": "docx"}], "RedirectUrl", "RedirectMethod": "POST"}}, "data": {...}}`, the
   group and template by name. Answer `{"ticket": "<id>"}`; ZAC hands the browser
   `{base}/smartdocuments/wizard?ticket=<id>`.
3. `GET {base}/smartdocuments/result/show?id=<sdDocument>&format=<docx mime type>` without `Authorization`: the
   document, with `content-disposition: attachment; filename="<name>"`.

A 400 from SmartDocuments becomes a bad request ("check if the current user is allowed"), a 5xx a runtime error.

## Starting a document and the callback

- `POST /rest/document-creation/create-document-attended` with `{zaakUuid, taskId?, title, description?, author,
  creationDate, smartDocumentsTemplateGroupId, smartDocumentsTemplateId}` answers `{"redirectURL": ...}`. It needs the
  `creerenDocument` right, SmartDocuments on for the zaaktype (else 400 `msg.error.smartdocuments.disabled`) and a
  mapped template (else 400 `msg.error.smartdocuments.not.configured`).
- After the wizard, the browser POSTs `sdDocument=<id>` (form-encoded) to
  `{CONTEXT_URL}/rest/document-creation/smartdocuments/callback/zaak/{zaakUuid}[/task/{taskId}]?title=..&userName=..&creationDate=..&templateId=..&templateGroupId=..&documentCreationToken=..`.
  The callback needs no login (`zac/authentication/RequestAuthorizationFilter.kt`). The token is single use and
  valid 60 minutes. ZAC downloads the document (call 3), creates an enkelvoudiginformatieobject of the
  informatieobjecttype mapped to the template, links it to the zaak (and task), and answers 303 to
  `{CONTEXT_URL}/static/smart-documents-result.html?...&result=success`. An empty `sdDocument` gives
  `result=cancelled`, any error `result=failure`.
- Mapping per zaaktype (`zac/app/admin/ZaaktypeCmmnConfigurationRestService.kt`): `GET
  /rest/zaakafhandelparameters/smartdocuments-templates` (the live structure), `GET` and `POST
  /rest/zaakafhandelparameters/{zaaktypeUuid}/smartdocuments-templates-mapping` with
  `[{id, name, groups, templates: [{id, name, informatieObjectTypeUUID}]}]`; ZAC checks every group and template
  against the live structure. The per-zaaktype switch is `smartDocuments.{enabledGlobally, enabledForZaaktype}` in the
  zaakafhandelparameters.

## When SmartDocuments is down (CONT-045)

Starting a document or listing templates answers 500 `msg.error.server.generic` ("a technical error has
occurred"): ZAC 5.4.5 has no SmartDocuments-specific message, against the draaiboek's "gebruikersvriendelijke
melding". A failing download in the callback gives `result=failure`. No timeout is configured on the client.
