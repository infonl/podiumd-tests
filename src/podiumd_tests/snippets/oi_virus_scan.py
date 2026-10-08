"""Open Inwoner's virus scan of uploads with ClamAV (SiteConfiguration.enable_virus_scan).

Actions: read (whether the scan is on), status, apply, remove. Params: action, clamav
("host:port" as Open Inwoner calls it; without it there is nothing to wire), record (old
values of the fields), which remove restores.
"""


def run(params):
    from open_inwoner.configurations.models import SiteConfiguration

    config = SiteConfiguration.get_solo()
    if params["action"] == "read":
        return config.enable_virus_scan
    wanted = _wanted(params.get("clamav"))
    if params["action"] == "status":
        return {"present": all(getattr(config, k) == v for k, v in wanted.items())}
    record = params.get("record") or {}
    if params["action"] == "remove":
        values = record
    else:
        record = record or {k: getattr(config, k) for k in wanted}
        values = wanted
    for field, value in values.items():
        setattr(config, field, value)
    config.save()
    return {"present": params["action"] == "apply", "record": record}


def _wanted(clamav):
    if not clamav:
        return {}
    host, port = clamav.rsplit(":", 1)
    return {"enable_virus_scan": True, "clamav_host": host, "clamav_port": int(port)}
