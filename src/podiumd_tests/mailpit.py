"""Finding and deleting messages in the environment's Mailpit SMTP sink."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from podiumd_tests.json_data import entries
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.json_data import JsonObject


def wait_for_subject(mailpit: ApiClient, subject: str, *, timeout: float) -> JsonObject:
    """The first message with exactly this subject; WaitTimeoutError when none arrives in time."""

    def found() -> JsonObject | None:
        page = mailpit.get("search", {"query": f'subject:"{subject}"'})
        return next((m for m in entries(page.get("messages")) if m.get("Subject") == subject), None)

    return wait_until(found, timeout=timeout, interval=1, description=f"mail {subject!r} in Mailpit")


def delete_message(mailpit: ApiClient, message_id: str) -> None:
    """Delete one message."""
    mailpit.request("DELETE", "messages", HTTPStatus.OK, json={"IDs": [message_id]})
