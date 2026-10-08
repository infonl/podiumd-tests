"""Read-only: each zgw_consumers Service's api_root as reached from this app. Params: none.

Returns [{slug, api_root, outcome}]; outcome "ok" for any answer below 500.
"""


def run(params):
    import requests

    from zgw_consumers.models import Service

    del params  # run() takes params like every snippet; this one has none
    found = []
    for service in Service.objects.order_by("slug"):
        try:
            status = requests.get(service.api_root, timeout=5).status_code
            outcome = "ok" if status < 500 else f"http {status}"
        except requests.RequestException as exc:
            outcome = type(exc).__name__
        found.append({"slug": service.slug, "api_root": service.api_root, "outcome": outcome})
    return found
