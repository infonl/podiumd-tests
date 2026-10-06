"""Bootstrap step: a ZGW JWT client (vng_api_common Applicatie and JWTSecret), e.g. in Open Notificaties.

Actions: status, apply (replaces the client), remove. Params: action,
client_id, scopes ({component: [scope, ...]}), secret (apply only).
"""


def run(params):
    from vng_api_common.authorizations.models import Applicatie
    from vng_api_common.authorizations.models import Autorisatie
    from vng_api_common.models import JWTSecret

    client_id = params["client_id"]
    applicaties = Applicatie.objects.filter(client_ids__contains=[client_id])
    secrets = JWTSecret.objects.filter(identifier=client_id)
    if params["action"] == "status":
        return {"present": applicaties.exists() and secrets.exists()}
    if params["action"] == "remove":
        return {"removed": applicaties.delete()[0] + secrets.delete()[0]}
    applicaties.delete()
    applicatie = Applicatie.objects.create(label=client_id, client_ids=[client_id], heeft_alle_autorisaties=False)
    for component, scopes in params["scopes"].items():
        Autorisatie.objects.create(applicatie=applicatie, component=component, scopes=scopes)
    JWTSecret.objects.update_or_create(identifier=client_id, defaults={"secret": params["secret"]})
    return {"present": True}
