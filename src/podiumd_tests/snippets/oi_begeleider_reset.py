"""Delete the plans of an Open Inwoner test begeleider and drop its contacts and contact requests.

Params: email (the begeleider's account). Returns the number of plans deleted.
"""


def run(params):
    from open_inwoner.accounts.models import User
    from open_inwoner.plans.models import Plan

    begeleider = User.objects.get(email=params["email"])
    deleted, _ = Plan.objects.filter(created_by=begeleider).delete()
    begeleider.user_contacts.clear()
    begeleider.contacts_for_approval.clear()
    return {"plans": deleted}
