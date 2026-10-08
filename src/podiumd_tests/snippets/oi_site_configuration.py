"""Open Inwoner's SiteConfiguration: set fields and return their old values. Params: fields ({name: value})."""


def run(params):
    from open_inwoner.configurations.models import SiteConfiguration

    config = SiteConfiguration.get_solo()
    old = {name: getattr(config, name) for name in params["fields"]}
    for name, value in params["fields"].items():
        setattr(config, name, value)
    config.save()
    return old
