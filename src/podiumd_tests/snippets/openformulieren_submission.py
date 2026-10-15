"""One Open Formulieren submission. Params: uuid, action.

Actions: delete; registration (its registration_status and, when failed, the first error line
of the traceback: the root cause, before the RegistrationFailed it raised); report (whether its
report row exists, its file name and whether this pod sees the file). Open Zaak numbers zaken from the highest identificatie, so after a test deletes its zaak
the number comes back; a submission kept with that public reference then blocks a new registration.
"""


def run(params):
    from openforms.submissions.models import Submission

    submissions = Submission.objects.filter(uuid=params["uuid"])
    if params["action"] == "delete":
        return {"removed": submissions.delete()[0]}
    submission = submissions.get()
    if params["action"] == "report":
        from openforms.submissions.models import SubmissionReport

        report = SubmissionReport.objects.filter(submission=submission).first()
        if report is None:
            return {"report": False, "file": "", "on_disk": False}
        name = report.content.name or ""
        return {"report": True, "file": name, "on_disk": bool(name) and report.content.storage.exists(name)}
    import re

    traceback = str((submission.registration_result or {}).get("traceback") or "")
    errors = [line for line in traceback.splitlines() if re.match(r"[\w.]+(Error|Exception|Failed)\b", line)]
    return {"status": submission.registration_status, "error": errors[0] if errors else ""}
