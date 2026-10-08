"""Whether Open Inwoner scans uploads with ClamAV (SiteConfiguration.enable_virus_scan). Params: none."""


def run(params):  # noqa: ARG001  # every snippet takes params
    from open_inwoner.configurations.models import SiteConfiguration

    return SiteConfiguration.get_solo().enable_virus_scan
