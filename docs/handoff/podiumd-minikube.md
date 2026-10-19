# Requests for podiumd-minikube

## Open Klant has the actor that OMC_ACTOR_ID names

After a delivery receipt (`POST /Notify/Confirm`) OMC registers a klantcontact in Open Klant and then links its
actor `OMC_ACTOR_ID` (`omc.settings.omc.actor.id`, `3a91832c-f2bd-4f22-8d5b-557b44c0ed38` on minikube) through
`POST actorklantcontacten`. Without that actor Open Klant answers 400 "Actor object bestaat niet." and OMC answers
the receipt with 500 (seen on minikube, 2026-10-19). podiumd-tests' `test_delivery_receipt_becomes_a_klantcontact`
skips until the actor exists.

Either create an actor in Open Klant and set `omc.settings.omc.actor.id` to its uuid, or create the actor with that
uuid (Open Klant's API assigns uuids itself, so this needs Open Klant's Django shell or admin), for example a
`geautomatiseerde_actor` named "OMC". ExternalsPodiumD icat ontw uses the same actor id.
