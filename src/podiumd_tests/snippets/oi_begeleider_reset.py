"""Delete the plans of an Open Inwoner test begeleider and drop its contacts and contact requests.

Also lifts the begeleider's contact request throttle (one per 60 s, from 2.5.0).
Params: email (the begeleider's account). Returns the number of plans deleted.
"""


def run(params):
    from django.conf import settings
    from django.core.cache import caches
    from open_inwoner.accounts.models import User
    from open_inwoner.plans.models import Plan

    begeleider = User.objects.get(email=params["email"])
    deleted, _ = Plan.objects.filter(created_by=begeleider).delete()
    begeleider.user_contacts.clear()
    begeleider.contacts_for_approval.clear()
    if "notification_throttle" in settings.CACHES:
        caches["notification_throttle"].delete(f"contact_request_{begeleider.pk}")
    return {"plans": deleted}
