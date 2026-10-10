"""podiumd-tests' Worldline merchant and webhook key in Open Formulieren; the webhook receiver plays Worldline.

Params: action (status, apply, remove), pspid (also the label and the webhook key id), endpoint (the
receiver's in-cluster root URL: Worldline's SDK refuses an endpoint with a path); for apply also
secret, used as API secret and webhook key secret.
"""


def run(params):
    from openforms.payments.contrib.worldline.models import WorldlineMerchant
    from openforms.payments.contrib.worldline.models import WorldlineWebhookConfiguration

    merchants = WorldlineMerchant.objects.filter(pspid=params["pspid"])
    webhooks = WorldlineWebhookConfiguration.objects.filter(pspid=params["pspid"])
    if params["action"] == "status":
        current = merchants.filter(endpoint=params["endpoint"]).exists()
        return {"present": current and webhooks.exists()}
    merchants.delete()
    webhooks.delete()
    if params["action"] == "remove":
        return {"present": False}
    WorldlineMerchant.objects.create(
        label=params["pspid"],
        pspid=params["pspid"],
        api_key=params["pspid"],
        api_secret=params["secret"],
        endpoint=params["endpoint"],
    )
    WorldlineWebhookConfiguration.objects.create(
        pspid=params["pspid"], webhook_key_id=params["pspid"], webhook_key_secret=params["secret"]
    )
    return {"present": True}
