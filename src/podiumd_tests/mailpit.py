"""Finding and deleting messages in the environment's Mailpit SMTP sink."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.clients.platform import mailpit_client
from podiumd_tests.json_data import entries
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry


def wait_for_mail(
    mailpit: ApiClient, *, timeout: float, subject: str | None = None, to: str | None = None
) -> JsonObject:
    """The first message with exactly this subject and/or to this address; WaitTimeoutError if none arrives in time."""
    query = " ".join(f'{field}:"{value}"' for field, value in (("subject", subject), ("to", to)) if value)

    def found() -> JsonObject | None:
        page = mailpit.get("search", {"query": query})
        return next((m for m in entries(page.get("messages")) if subject in {None, m.get("Subject")}), None)

    return wait_until(found, timeout=timeout, interval=1, description=f"mail {query} in Mailpit")


def delete_message(mailpit: ApiClient, message_id: str) -> None:
    """Delete one message."""
    mailpit.request("DELETE", "messages", HTTPStatus.OK, json={"IDs": [message_id]})


def received(
    mailpit: ApiClient, registry: ResourceRegistry, *, timeout: float, to: str, subject: str | None = None
) -> str:
    """The HTML of the first mail to the address (wait_for_mail); cleanup deletes every mail to the address."""
    message = wait_for_mail(mailpit, timeout=timeout, to=to, subject=subject)
    registry.add(f"mail to {to}", lambda: delete_mails(mailpit, f'to:"{to}"'))
    return str(mailpit.get(f"message/{message['ID']}").get("HTML"))


def delete_mails(mailpit: ApiClient, query: str) -> None:
    """Delete every message a Mailpit search finds."""
    mailpit.request("DELETE", "search", HTTPStatus.OK, params={"query": query})


def forget_mails(env: Environment, registry: ResourceRegistry, query: str) -> None:
    """Delete, at cleanup, the mails a Mailpit search finds; nothing where the environment has no Mailpit.

    For mails an app sends as a side effect, which the test does not read.
    """
    if env.capabilities.skip_reason("mailpit") is None:
        registry.add(f"mails {query}", lambda: delete_mails(mailpit_client(env), query))
