"""Run Open Formulieren's data removal task (delete_submissions) for one submission's age.

Params: uuid, age_days (set the submission's created_on that many days back first; 0 keeps it).
Returns whether the submission is still there. The task removes only what is past its form's limit.
"""


def run(params):
    from datetime import timedelta

    from django.utils import timezone
    from openforms.data_removal.tasks import delete_submissions
    from openforms.submissions.models import Submission

    submissions = Submission.objects.filter(uuid=params["uuid"])
    if params["age_days"]:
        submissions.update(created_on=timezone.now() - timedelta(days=params["age_days"]))
    delete_submissions()
    return {"kept": submissions.exists()}
