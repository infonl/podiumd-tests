"""Bootstrap step: an API token (TokenAuth) in Open Klant, Objecttypen or Objecten.

Actions: status, apply (replaces the token), remove. Params: action, module
(the app's token models module), identifier, secret (the token; apply only).
"""


def run(params):
    import importlib

    token_auth = importlib.import_module(params["module"]).TokenAuth
    tokens = token_auth.objects.filter(identifier=params["identifier"])
    if params["action"] == "status":
        return {"present": tokens.exists()}
    if params["action"] == "remove":
        return {"removed": tokens.delete()[0]}
    tokens.delete()
    token_auth.objects.create(
        identifier=params["identifier"],
        token=params["secret"],
        contact_person="podiumd-tests",
        email="podiumd-tests@example.invalid",
    )
    return {"present": True}
