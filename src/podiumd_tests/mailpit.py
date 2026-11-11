"""Finding and deleting messages in the environment's Mailpit SMTP sink."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import cast

from podiumd_tests.clients.platform import mailpit_client
from podiumd_tests.django_snippets import run_snippet
from podiumd_tests.json_data import entries
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def quoted(value: str) -> str:
    """Return value as one Mailpit search phrase."""
    return f'"{value}"'  # noqa: B907  # Mailpit search syntax, not a Python literal


def wait_for_mail(
    mailpit: ApiClient, *, timeout: float, subject: str | None = None, to: str | None = None
) -> JsonObject:
    """Return the first message with exactly this subject and/or to this address; WaitTimeoutError if none arrives."""
    criteria = (("subject", subject), ("to", to))
    query = " ".join(f"{field}:{quoted(value)}" for field, value in criteria if value)

    def found() -> JsonObject | None:
        page = mailpit.get("search", {"query": query})
        messages = entries(page.get("messages"))
        return next((message for message in messages if subject in {None, message.get("Subject")}), None)

    return wait_until(found, timeout=timeout, interval=1, description=f"mail {query} in Mailpit")


def delete_message(mailpit: ApiClient, message_id: str) -> None:
    """Delete one message."""
    mailpit.request("DELETE", "messages", HTTPStatus.OK, json={"IDs": [message_id]})


def received_message(
    mailpit: ApiClient, registry: ResourceRegistry, *, timeout: float, to: str, subject: str | None = None
) -> JsonObject:
    """Return the first mail to the address (wait_for_mail) with headers, HTML and attachments; cleanup deletes
    every mail to the address.
    """
    message = wait_for_mail(mailpit, timeout=timeout, to=to, subject=subject)
    registry.add(f"mail to {to}", lambda: delete_mails(mailpit, f"to:{quoted(to)}"))
    return mailpit.get(f"message/{message['ID']}")


def received(
    mailpit: ApiClient, registry: ResourceRegistry, *, timeout: float, to: str, subject: str | None = None
) -> str:
    """Return the HTML of the first mail to the address (received_message)."""
    return str(received_message(mailpit, registry, timeout=timeout, to=to, subject=subject).get("HTML"))


def delete_mails(mailpit: ApiClient, query: str) -> None:
    """Delete every message a Mailpit search finds."""
    mailpit.request("DELETE", "search", HTTPStatus.OK, params={"query": query})


def forget_mails(env: Environment, registry: ResourceRegistry, query: str) -> None:
    """Delete, at cleanup, the mails a Mailpit search finds; nothing where the environment has no Mailpit.

    For mails an app sends as a side effect, which the test does not read.
    """
    if env.capabilities.skip_reason("mailpit") is None:
        registry.add(f"mails {query}", lambda: delete_mails(mailpit_client(env), query))


def mail_queue(env: Environment, component: str, action: str, text: str) -> list[str]:
    """Status, retry or delete (action) the mails mentioning text in the app's django_yubin queue; their statuses."""
    params: dict[str, object] = {"action": action, "text": text}
    result = cast("dict[str, list[str]]", run_snippet(env.kube, env.deployment_for(component), "mail_queue", params))
    return result.get("status", [])
