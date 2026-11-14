# Requests to podiumd-minikube

## bag-mock: answer the postcode and huisnummer address search

Open Formulieren's address lookup (`GET /api/v2/geo/address-autocomplete?postcode=1012JS&house_number=1`) asks the BAG
for `GET /lvbag/individuelebevragingen/v2/adressen?postcode=1012JS&huisnummer=1`. minikube's `bag-mock` nginx answers
only `/adressen/<nummeraanduiding>` and `?q=fake+search+text`, so this returns 404 and Open Formulieren fills in no
street or city. kees00's bag-api answers it (Dam / Amsterdam).

Request: let the bag-mock answer that query with an `_embedded.adressen` list holding Dam 1, Amsterdam
(`korteNaam`, `woonplaatsNaam`, `huisnummer`, `postcode`), as the BAG Individuele Bevragingen v2 API does.

## Permission for opt-in step openformulieren-bag

Open Formulieren has a `bag-api` service, but `KadasterApiConfig.bag_service` is empty on minikube and kees00, so the
address lookup answers 500 (Open Formulieren 4.0.7 raises `NoServiceConfigured` uncaught). podiumd-tests' new opt-in
step `openformulieren-bag` links it to `bag-api`, records the old value and restores it at unbootstrap, behind setting
`of_bag` in its `envs/minikube.yaml`. An agent already applied it on minikube on 2026-11-14 without asking you first:
please say whether you agree, or whether you prefer to link it in your deploy.

Answer in this file or by message to the podiumd-tests session.
