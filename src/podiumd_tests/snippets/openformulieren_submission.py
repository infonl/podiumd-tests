"""One Open Formulieren submission. Params: uuid, action.

Actions: delete; registration (its registration_status, failed also when a component's pre-registration failed,
and then the first error line of the traceback: the root cause, before the RegistrationFailed it raised); report (whether its
report row exists, its file name, whether this pod sees the file and its modification time,
the pod, and the other submissions whose report has the same file name). Open Zaak numbers zaken from the highest identificatie, so after a test deletes its zaak
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
        import socket

        name = report.content.name or ""
        storage = report.content.storage
        on_disk = bool(name) and storage.exists(name)
        same_name = SubmissionReport.objects.filter(content=name).exclude(pk=report.pk)
        return {
            "report": True,
            "file": name,
            "on_disk": on_disk,
            "modified": storage.get_modified_time(name).isoformat() if on_disk else "",
            "pod": socket.gethostname(),
            "same_name": [str(other.submission.uuid) for other in same_name],
        }
    import re

    # A component's own registration step (a customerProfile's write to Open Klant) fails apart from the backend's.
    failed = submission.submissionvaluevariable_set.filter(pre_registration_status="failed")
    results = [submission.registration_result, *(variable.pre_registration_result for variable in failed)]
    traceback = "\n".join(str((result or {}).get("traceback") or "") for result in results)
    errors = [line for line in traceback.splitlines() if re.match(r"[\w.]+(Error|Exception|Failed)\b", line)]
    status = "failed" if failed.exists() else submission.registration_status
    return {"status": status, "error": errors[0] if errors else ""}
