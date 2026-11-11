"""Open Archiefbeheer's review response task: whether it waits for the commit, or process a stuck one now.

Params: action "on_commit" (no other params) or "process" (uuid of the list).
"""


def run(params):
    import inspect

    from openarchiefbeheer.destruction.api.serializers import ReviewResponseSerializer
    from openarchiefbeheer.destruction.constants import ListStatus
    from openarchiefbeheer.destruction.models import DestructionList
    from openarchiefbeheer.destruction.models import ReviewResponse
    from openarchiefbeheer.destruction.tasks import process_review_response

    if params["action"] == "on_commit":
        return "on_commit" in inspect.getsource(ReviewResponseSerializer.create)
    # The task also assigns the list's next reviewer, so it runs only on a list still waiting for it.
    destruction_list = DestructionList.objects.get(uuid=params["uuid"])
    if destruction_list.status != ListStatus.changes_requested:
        return False
    response = ReviewResponse.objects.filter(review__destruction_list=destruction_list).latest("pk")
    process_review_response(response.pk)
    return True
