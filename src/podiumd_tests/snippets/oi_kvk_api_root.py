"""Open Inwoner's KvKConfig.api_root: the KvK API it reads company names from; empty when unset."""


def run(params):
    from open_inwoner.kvk.models import KvKConfig

    del params
    return KvKConfig.get_solo().api_root or ""
