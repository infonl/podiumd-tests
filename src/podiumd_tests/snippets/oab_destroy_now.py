"""Destroy one queued vernietigingslijst now instead of after WAITING_PERIOD days.

Does what the periodic task queue_destruction_lists_for_deletion does on the planned date,
for this list only. Params: uuid.
"""


def run(params):
    import datetime

    from openarchiefbeheer.destruction.models import DestructionList
    from openarchiefbeheer.destruction.tasks import delete_destruction_list

    destruction_list = DestructionList.objects.get(uuid=params["uuid"])
    # The same local date the periodic task compares with.
    destruction_list.planned_destruction_date = datetime.date.today()  # noqa: DTZ011
    destruction_list.save()
    delete_destruction_list(destruction_list)
    return str(destruction_list.processing_status)
