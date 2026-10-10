"""podiumd-tests' Ogone merchant in Open Formulieren; the tests play Ogone.

Params: action (status, apply, remove), label, pspid, hash_algorithm, endpoint; for apply also
secret, used as both SHA-IN and SHA-OUT passphrase. Open Formulieren never calls the endpoint.
"""


def run(params):
    from openforms.payments.contrib.ogone.models import OgoneMerchant

    merchants = OgoneMerchant.objects.filter(label=params["label"])
    if params["action"] == "status":
        return {"present": merchants.exists()}
    merchants.delete()
    if params["action"] == "remove":
        return {"present": False}
    OgoneMerchant.objects.create(
        label=params["label"],
        pspid=params["pspid"],
        sha_in_passphrase=params["secret"],
        sha_out_passphrase=params["secret"],
        hash_algorithm=params["hash_algorithm"],
        endpoint_custom=params["endpoint"],
    )
    return {"present": True}
