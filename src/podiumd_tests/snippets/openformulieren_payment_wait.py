"""Open Formulieren's wait_for_payment_to_register: register a submission only once it is paid.

Record mode: apply switches it on and records the old value; remove puts that back while the
setting is still on.
"""


def run(params):
    from openforms.config.models import GlobalConfiguration

    config = GlobalConfiguration.get_solo()
    record = params.get("record") or {}
    if params["action"] == "status":
        return {"present": config.wait_for_payment_to_register}
    if params["action"] == "apply":
        if not config.wait_for_payment_to_register:
            record.setdefault("old", False)
            config.wait_for_payment_to_register = True
            config.save()
        return {"present": True, "record": record}
    if "old" in record and config.wait_for_payment_to_register:
        config.wait_for_payment_to_register = record["old"]
        config.save()
    return {"present": False}
