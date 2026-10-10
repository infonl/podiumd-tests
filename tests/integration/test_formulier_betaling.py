"""Payments in Open Formulieren through Ogone (legacy), with podiumd-tests playing Ogone for its test merchant.

A form with a price asks for a payment after it is completed. Open Formulieren creates the zaak
right away (ZGW pre-registration: its identificatie is the public reference); with the profile
setting of_wait_for_payment it adds the rest (rollen, status, documents) only once the payment completed.
"""

from __future__ import annotations

import secrets

from typing import TYPE_CHECKING

import pytest

from podiumd_tests.bootstrap.names import OGONE_MERCHANT
from podiumd_tests.bootstrap.names import OGONE_STORE_KEY
from podiumd_tests.bootstrap.names import PREFIX
from podiumd_tests.bootstrap.steps import NAW
from podiumd_tests.bootstrap.steps import NAW_DATA
from podiumd_tests.bootstrap.steps import ZGW_REGISTRATION
from podiumd_tests.openformulieren import form_and_headers
from podiumd_tests.openformulieren import make_form
from podiumd_tests.openformulieren import registered_zaak
from podiumd_tests.openformulieren import registration_state
from podiumd_tests.openformulieren import submit
from podiumd_tests.openformulieren import wait_for_registration
from podiumd_tests.payments import OGONE_ENDPOINT
from podiumd_tests.payments import ogone_feedback
from podiumd_tests.payments import ogone_return_url
from podiumd_tests.payments import ogone_shasign
from podiumd_tests.payments import payment_return
from podiumd_tests.payments import start_payment
from podiumd_tests.responses import expect_status
from podiumd_tests.wait import wait_until

if TYPE_CHECKING:
    from collections.abc import Callable

    from podiumd_tests.clients.api import ApiClient
    from podiumd_tests.environment import Environment
    from podiumd_tests.json_data import JsonObject
    from podiumd_tests.seed.registry import ResourceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.requires("openformulieren", "openzaak")]

REGISTRATION_TIMEOUT = 90
PRICE = "12.50"


class Payer:
    """An anonymous inwoner who completes the payment form, and Ogone for the payments they make."""

    def __init__(self, env: Environment, openzaak: ApiClient, registry: ResourceRegistry, slug: str) -> None:
        self.env, self.http, self.openzaak = env, env.session(), openzaak
        data = {"omschrijving": slug, **NAW_DATA}
        self.status = submit(env, self.http, registry, slug, data, timeout=REGISTRATION_TIMEOUT, registers=False)
        # The zaak of the pre-registration, deleted with the submission.
        self.zaak = registered_zaak(env, openzaak, registry, self.status)
        _, self.headers = form_and_headers(self.http, env.profile.urls["openformulieren"], slug)
        self.passphrase = env.credentials.get(OGONE_STORE_KEY)

    @property
    def submission(self) -> str:
        """The submission's uuid."""
        return str(self.status["submission"])

    def request(self) -> tuple[JsonObject, dict[str, str]]:
        """A new payment request: where the browser posts the form to, and the form's fields."""
        request = start_payment(self.http, str(self.status["paymentUrl"]), self.headers)
        return request, {k: str(v) for k, v in dict(request["data"]).items()}  # type: ignore[arg-type]

    def pay(self, outcome: str, status: str) -> tuple[str, dict[str, str]]:
        """Pay; Ogone returns with outcome and STATUS. The ORDERID, and what the form is told."""
        _, data = self.request()
        return data["ORDERID"], payment_return(self.http, ogone_return_url(data, outcome, status, self.passphrase))

    def webhook(self, order_id: str, status: str) -> None:
        """Ogone's server-to-server feedback on the payment."""
        url = f"{self.env.profile.urls['openformulieren']}/payment/ogone-legacy/webhook"
        expect_status(self.http.post(url, data=ogone_feedback(order_id, status, self.passphrase)), 200)

    def registration_status(self) -> str:
        """Open Formulieren's registration status of the submission."""
        return registration_state(self.env, self.submission)["status"]

    def registered(self) -> JsonObject:
        """The zaak once the registration finished: with status."""
        wait_for_registration(self.env, self.submission, timeout=REGISTRATION_TIMEOUT)
        return self.openzaak.get(str(self.zaak["url"]))


@pytest.fixture(name="payment_form")
def fixture_payment_form(
    podiumd_env: Environment, registry: ResourceRegistry, need_bootstrap: Callable[..., None]
) -> str:
    """A form with a price, paid through the test merchant, that registers a zaak of the test zaaktype."""
    if not podiumd_env.profile.allows("of_wait_for_payment"):
        pytest.skip("profile setting of_wait_for_payment is off: Open Formulieren registers before the payment")
    need_bootstrap(
        "openformulieren-zgw-group", "openzaak-of-autorisatie", "openformulieren-ogone", "openformulieren-payment-wait"
    )
    slug = registry.tagged(f"betaling-{secrets.token_hex(3)}")
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"}
    payment = {"backend": "ogone-legacy", "merchant": OGONE_MERCHANT, "price": PRICE}
    make_form(podiumd_env, registry, slug, [field, *NAW], ZGW_REGISTRATION, payment=payment)
    return slug


@pytest.mark.tc("OF-021", "INT-008")
def test_form_asks_for_an_ogone_payment(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: str
) -> None:
    """The completed form sends the inwoner to Ogone with the price, signed for the merchant; unpaid, it stops there."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    request, data = payer.request()
    assert (request["type"], request["url"]) == ("post", OGONE_ENDPOINT)
    assert (data["PSPID"], data["AMOUNT"], data["CURRENCY"]) == (PREFIX, "1250", "EUR")
    assert data["SHASIGN"] == ogone_shasign(data, payer.passphrase)
    assert payer.registration_status() == "pending"
    assert (payer.zaak["status"], payer.zaak["betalingsindicatie"]) == (None, "nog_niet")


@pytest.mark.xfail(
    strict=True,
    reason="Open Formulieren 3.5.5's ZGW registration creates the zaak when the form is completed, before the"
    " payment (pre-registration), also with wait_for_payment_to_register; the draaiboek expects no zaak",
)
@pytest.mark.tc("OF-022")
def test_unpaid_form_leaves_no_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: str
) -> None:
    """A completed form that is not paid creates no zaak, so ZAC shows none."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    assert not payer.zaak, f"zaak {payer.zaak['identificatie']} exists"


@pytest.mark.tc("OF-027")
def test_paid_form_registers_a_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: str
) -> None:
    """After Ogone's status 9 the form shows the payment completed, and the zaak is registered."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    _, told = payer.pay("accept", "9")
    assert (told["of_payment_status"], told["of_payment_action"]) == ("completed", "accept")
    assert payer.registered()["status"]


@pytest.mark.xfail(
    strict=True,
    reason="with wait_for_payment_to_register on, Open Formulieren 3.5.5 skips its payment status update"
    " (update_submission_payment_status), so the pre-registered zaak stays betalingsindicatie nog_niet after"
    " the payment; not yet reported upstream",
)
@pytest.mark.tc("OF-024")
def test_zaak_of_a_paid_form_is_marked_paid(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: str
) -> None:
    """The zaak of a paid form shows it is fully paid, which ZAC displays."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    payer.pay("accept", "9")
    zaak = payer.registered()
    wait_until(
        lambda: openzaak.get(str(zaak["url"]))["betalingsindicatie"] == "geheel",
        timeout=REGISTRATION_TIMEOUT,
        description=f"zaak {zaak['identificatie']} marked fully paid",
    )


@pytest.mark.parametrize(
    ("outcome", "ogone_status", "told_status"),
    [
        pytest.param("exception", "92", "processing", id="uncertain", marks=pytest.mark.tc("OF-025")),
        pytest.param("decline", "2", "failed", id="refused", marks=pytest.mark.tc("OF-026")),
        pytest.param("exception", "52", "processing", id="exception", marks=pytest.mark.tc("OF-028")),
        pytest.param("cancel", "1", "failed", id="cancelled", marks=pytest.mark.tc("OF-023", "OF-029")),
        pytest.param("decline", "93", "failed", id="failure", marks=pytest.mark.tc("OF-030")),
    ],
)
def test_unpaid_form_tells_the_inwoner_and_registers_nothing(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures and parameters
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    payment_form: str,
    outcome: str,
    ogone_status: str,
    told_status: str,
) -> None:
    """The form is told the payment's status, to show a message or the payment again; the registration waits.

    After a failed payment the inwoner can start a new one.
    """
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    _, told = payer.pay(outcome, ogone_status)
    assert told["of_payment_status"] == told_status
    if told_status == "failed":
        assert payer.request()[0]["type"] == "post"
    assert payer.registration_status() == "pending"


@pytest.mark.tc("OF-025")
def test_uncertain_payment_registers_once_ogone_confirms_it(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: str
) -> None:
    """After status 92, Ogone's webhook reports status 9: then the zaak is registered."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    order_id, told = payer.pay("exception", "92")
    assert told["of_payment_status"] == "processing"
    payer.webhook(order_id, "9")
    assert payer.registered()["status"]
