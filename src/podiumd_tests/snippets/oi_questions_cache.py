"""Forget Open Inwoner's cached Mijn vragen of a partij; Open Inwoner before 2.5.0 has no such cache.

Params: partij (UUID).
"""


def run(params):
    from open_inwoner.openklant.services import OpenKlant2Service

    service = OpenKlant2Service()
    if hasattr(service, "invalidate_questions_cache"):
        service.invalidate_questions_cache(params["partij"])
