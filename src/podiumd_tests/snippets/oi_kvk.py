"""Open Inwoner's KvK API (KvKConfig), from which an eHerkenning login gets the company's names.

Actions: status, apply, remove. Params: action, api_root (as Open Inwoner calls it; without it
there is nothing to wire), record ({"api_root": old value}), which remove restores.
"""


def run(params):
    from open_inwoner.kvk.models import KvKConfig

    config = KvKConfig.get_solo()
    wanted = params.get("api_root") or ""
    if params["action"] == "status":
        return {"present": not wanted or config.api_root == wanted}
    record = params.get("record") or {}
    if params["action"] == "remove":
        if "api_root" in record:
            config.api_root = record["api_root"]
            config.save()
        return {"present": False}
    if wanted:
        record.setdefault("api_root", config.api_root)
        config.api_root = wanted
        config.save()
    return {"present": True, "record": record}
