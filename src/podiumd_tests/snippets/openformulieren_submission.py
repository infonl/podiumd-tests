"""Delete one Open Formulieren submission. Params: uuid.

Open Zaak numbers zaken from the highest identificatie, so after a test deletes its zaak the
number comes back; a submission kept with that public reference then blocks a new registration.
"""


def run(params):
    from openforms.submissions.models import Submission

    return {"removed": Submission.objects.filter(uuid=params["uuid"]).delete()[0]}
