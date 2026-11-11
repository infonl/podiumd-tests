"""Appended to a bootstrap step snippet for action ensure: status, then apply only when the step is missing.

Params: the step snippet's, and stored (the step's credentials are in the credentials Secret; without
them the step is missing). Returns apply's result with created true, or {"created": false}.
"""

_step_run = run  # the step snippet's run, defined before this source


def run(params):
    if _step_run({**params, "action": "status"})["present"] and params["stored"]:
        return {"created": False}
    return {**_step_run({**params, "action": "apply"}), "created": True}
