# Requests to podiumd-minikube

## Subscribe Open Inwoner to Open Notificaties (zaak notifications through the portal)

The draaiboek lets a gemeente choose who notifies the burger of a status change or a new document: the portal (Open
Inwoner), the bronsysteem (OMC) or both (OI-041 to OI-044). Today only OMC can: no environment subscribes Open Inwoner
to Open Notificaties (minikube, kees00, ExternalsPodiumD), so Open Inwoner 2.5.0's own notifications never run.

Request: wire Open Inwoner the way an estate would for a gemeente that chooses portal notifications:

- an Open Notificaties abonnement on kanaal `zaken` with callback Open Inwoner's
  `/api/openzaak/notifications/webhook/zaken` and an auth Open Inwoner accepts;
- in Open Inwoner, `NotificationsConfig.notifications_api_service` pointing to Open Notificaties and the matching
  `notifications.Subscription` (its webhook checks the caller's token against it, `open_inwoner/openzaak/auth.py`);
- keep `OpenZaakConfig.skip_notification_statustype_informeren` and the mail settings as they are; mail goes to Mailpit.

podiumd-tests then switches portal notifications on or off per zaaktype with its own run-tagged `ZaakTypeConfig` and
`ZaakTypeStatusTypeConfig`, so other zaaktypen keep their behaviour. Its tests show only OMC, only the portal, and
both, plus the portal's document notification (OI-042).

Answer: yes or no in this file (or by message to the podiumd-tests session).
