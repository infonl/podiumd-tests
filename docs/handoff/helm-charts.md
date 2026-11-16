# Handoff to helm-charts

Open items for the helm-charts session. Delete an item when it is done; delete the file when nothing is open.

## helm-charts #719 (ZAC 5.12.0) at b9567fff: recheck on minikube, 2026-11-16

Deployed by podiumd-minikube at 17:08 CET (Gotenberg 9.4.1, OPA 1.22.3-static, otel-collector 0.165.0; Open Zaak
1.31.1, OMC 2.4.1, Open Klant 2.19.2).

1. podiumd-chart-45: fixed. Converted Word, Excel and PowerPoint files and kept mails claim PDF/A-2b and PDF/UA-1
   again (14 of 15 PDF/A tests pass; the 15th is zac-44 below).
2. podiumd-chart-39: within the limit. A Word file of 50 text pages and 40 photos of 4000x3000 (127 MB) peaks at
   1,665 MiB anon on Gotenberg 9.4.1 (1,625 MiB on 8.38.1), converts in 6 s, no restart, 2Gi limit.
3. zac-42: no difference; #719 stays draft for it.
4. ZAC 5.12 component suite: passes except zac-42 and zac-44.

New: zac-44 (High, podiumd-known-issues). ZAC's convert to PDF answers 500 when the PDF is above about 1.9 MB: ZAC
sends it inline to Open Zaak, and Open Zaak 1.31.1 refuses request bodies above Django's default 2,621,440 bytes
(`DATA_UPLOAD_MAX_MEMORY_SIZE`, `RequestDataTooBig`), with no setting to raise it. Gotenberg 9's native PDF/A+UA
output is larger, so more documents cross it. There is no chart fix; it needs ZAC (bestandsdelen) or Open Zaak (a
configurable limit). Keeping Gotenberg 8 is no option (it loses PDF/A for every document). Suggested: a line in the
4.11.0 release notes ("Bekende problemen").
