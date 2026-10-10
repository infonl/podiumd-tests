"""Payments in Open Formulieren through Ogone (legacy) and Worldline, with podiumd-tests playing both providers.

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
from podiumd_tests.bootstrap.names import WORLDLINE_MERCHANT
from podiumd_tests.bootstrap.names import WORLDLINE_STORE_KEY
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
from podiumd_tests.payments import WORLDLINE_REDIRECT
from podiumd_tests.payments import form_fields
from podiumd_tests.payments import ogone_feedback
from podiumd_tests.payments import ogone_return_url
from podiumd_tests.payments import ogone_shasign
from podiumd_tests.payments import payment_return
from podiumd_tests.payments import start_payment
from podiumd_tests.payments import worldline_return_url
from podiumd_tests.payments import worldline_webhook
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
OGONE, WORLDLINE = "ogone-legacy", "worldline"
MERCHANTS = {OGONE: OGONE_MERCHANT, WORLDLINE: WORLDLINE_MERCHANT}
STEPS = {OGONE: "openformulieren-ogone", WORLDLINE: "openformulieren-worldline"}
# What the provider reports per outcome: Ogone's return URL and STATUS, Worldline's payment status.
OUTCOMES: dict[str, dict[str, tuple[str, str]]] = {
    OGONE: {
        "paid": ("accept", "9"),
        "uncertain": ("exception", "92"),
        "refused": ("decline", "2"),
        "exception": ("exception", "52"),
        "cancelled": ("cancel", "1"),
        "failure": ("decline", "93"),
    },
    WORLDLINE: {
        "paid": ("", "CAPTURED"),
        "uncertain": ("", "PENDING_CAPTURE"),
        "exception": ("", "REJECTED"),
        "cancelled": ("", "CANCELLED_BY_CONSUMER"),
        "failure": ("", "CANCELLED"),
    },
}


class Payer:
    """An anonymous inwoner who completes the payment form, and the provider for the payments they make."""

    def __init__(
        self, env: Environment, openzaak: ApiClient, registry: ResourceRegistry, form: tuple[str, str]
    ) -> None:
        self.backend, slug = form
        self.env, self.http, self.openzaak = env, env.session(), openzaak
        data = {"omschrijving": slug, **NAW_DATA}
        self.status = submit(env, self.http, registry, slug, data, timeout=REGISTRATION_TIMEOUT, registers=False)
        # The zaak of the pre-registration, deleted with the submission.
        self.zaak = registered_zaak(env, openzaak, registry, self.status)
        _, self.headers = form_and_headers(self.http, env.profile.urls["openformulieren"], slug)

    @property
    def secret(self) -> str:
        """The test merchant's passphrase or secret."""
        return self.env.credentials.get(OGONE_STORE_KEY if self.backend == OGONE else WORLDLINE_STORE_KEY)

    @property
    def submission(self) -> str:
        """The submission's uuid."""
        return str(self.status["submission"])

    def request(self) -> JsonObject:
        """A new payment request: {type, url, data}, where Open Formulieren sends the browser."""
        return start_payment(self.http, str(self.status["paymentUrl"]), self.headers)

    def pay(self, outcome: str) -> tuple[str, dict[str, str]]:
        """Pay; the provider reports the outcome. The payment's order reference, and what the form is told."""
        return_url, status = OUTCOMES[self.backend][outcome]
        request = self.request()
        if self.backend == OGONE:
            data = form_fields(request)
            url, reference = ogone_return_url(data, return_url, status, self.secret), data["ORDERID"]
        else:
            url, reference = worldline_return_url(self.env, str(request["url"]), status)
        return reference, payment_return(self.http, url)

    def confirm(self, reference: str) -> None:
        """The provider's webhook: the payment completed."""
        base = self.env.profile.urls["openformulieren"]
        if self.backend == OGONE:
            response = self.http.post(
                f"{base}/payment/{OGONE}/webhook", data=ogone_feedback(reference, "9", self.secret)
            )
        else:
            body, headers = worldline_webhook(reference, "CAPTURED", WORLDLINE_MERCHANT, self.secret)
            response = self.http.post(f"{base}/payment/{WORLDLINE}/webhook", data=body, headers=headers)
        expect_status(response, 200)

    def registration_status(self) -> str:
        """Open Formulieren's registration status of the submission."""
        return registration_state(self.env, self.submission)["status"]

    def registered(self) -> JsonObject:
        """The zaak once the registration finished: with status."""
        wait_for_registration(self.env, self.submission, timeout=REGISTRATION_TIMEOUT)
        return self.openzaak.get(str(self.zaak["url"]))


@pytest.fixture(name="payment_form")
def fixture_payment_form(
    request: pytest.FixtureRequest,
    podiumd_env: Environment,
    registry: ResourceRegistry,
    need_bootstrap: Callable[..., None],
) -> tuple[str, str]:
    """The payment backend (the test's parameter), and the slug of a form with a price paid through its merchant."""
    if not podiumd_env.profile.allows("of_wait_for_payment"):
        pytest.skip("profile setting of_wait_for_payment is off: Open Formulieren registers before the payment")
    backend = str(request.param)
    need_bootstrap(
        "openformulieren-zgw-group", "openzaak-of-autorisatie", "openformulieren-payment-wait", STEPS[backend]
    )
    slug = registry.tagged(f"betaling-{secrets.token_hex(3)}")
    field = {"type": "textfield", "key": "omschrijving", "label": "Omschrijving"}
    payment = {"backend": backend, "merchant": MERCHANTS[backend], "price": PRICE}
    make_form(podiumd_env, registry, slug, [field, *NAW], ZGW_REGISTRATION, payment=payment)
    return backend, slug


@pytest.mark.parametrize(
    "payment_form",
    [
        pytest.param(OGONE, id=OGONE, marks=pytest.mark.tc("OF-021", "INT-008")),
        pytest.param(WORLDLINE, id=WORLDLINE, marks=pytest.mark.tc("OF-054")),
    ],
    indirect=True,
)
def test_form_asks_for_a_payment(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: tuple[str, str]
) -> None:
    """The completed form sends the inwoner to the provider with the price; unpaid, it stops there.

    Ogone gets a form signed for the merchant; Worldline a hosted checkout.
    """
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    request = payer.request()
    if payer.backend == OGONE:
        data = form_fields(request)
        assert (request["type"], request["url"]) == ("post", OGONE_ENDPOINT)
        assert (data["PSPID"], data["AMOUNT"], data["CURRENCY"]) == (PREFIX, "1250", "EUR")
        assert data["SHASIGN"] == ogone_shasign(data, payer.secret)
    else:
        assert request["type"] == "get"
        assert str(request["url"]).startswith(WORLDLINE_REDIRECT)
    assert payer.registration_status() == "pending"
    assert (payer.zaak["status"], payer.zaak["betalingsindicatie"]) == (None, "nog_niet")


@pytest.mark.parametrize(
    "payment_form",
    [
        pytest.param(OGONE, id=OGONE, marks=pytest.mark.tc("OF-027")),
        pytest.param(WORLDLINE, id=WORLDLINE, marks=pytest.mark.tc("OF-060")),
    ],
    indirect=True,
)
def test_paid_form_registers_a_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: tuple[str, str]
) -> None:
    """Once paid, the form shows the payment completed, and the zaak is registered."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    _, told = payer.pay("paid")
    assert told["of_payment_status"] == "completed"
    assert payer.registered()["status"]


@pytest.mark.parametrize(
    ("payment_form", "outcome", "told_status"),
    [
        pytest.param(OGONE, "uncertain", "processing", id="ogone-uncertain", marks=pytest.mark.tc("OF-025")),
        pytest.param(OGONE, "refused", "failed", id="ogone-refused", marks=pytest.mark.tc("OF-026")),
        pytest.param(OGONE, "exception", "processing", id="ogone-exception", marks=pytest.mark.tc("OF-028")),
        pytest.param(OGONE, "cancelled", "failed", id="ogone-cancelled", marks=pytest.mark.tc("OF-023", "OF-029")),
        pytest.param(OGONE, "failure", "failed", id="ogone-failure", marks=pytest.mark.tc("OF-030")),
        pytest.param(WORLDLINE, "uncertain", "processing", id="worldline-uncertain", marks=pytest.mark.tc("OF-059")),
        pytest.param(WORLDLINE, "exception", "failed", id="worldline-exception", marks=pytest.mark.tc("OF-061")),
        pytest.param(
            WORLDLINE, "cancelled", "failed", id="worldline-cancelled", marks=pytest.mark.tc("OF-056", "OF-062")
        ),
        pytest.param(WORLDLINE, "failure", "failed", id="worldline-failure", marks=pytest.mark.tc("OF-063")),
    ],
    indirect=["payment_form"],
)
def test_unpaid_form_tells_the_inwoner_and_registers_nothing(  # pylint: disable=too-many-arguments,too-many-positional-arguments  # fixtures and parameters
    podiumd_env: Environment,
    openzaak: ApiClient,
    registry: ResourceRegistry,
    payment_form: tuple[str, str],
    outcome: str,
    told_status: str,
) -> None:
    """The form is told the payment's status, to show a message or the payment again; the registration waits.

    After a failed payment the inwoner can start a new one.
    """
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    _, told = payer.pay(outcome)
    assert told["of_payment_status"] == told_status
    if told_status == "failed":
        assert payer.request()["url"]
    assert payer.registration_status() == "pending"


@pytest.mark.parametrize(
    "payment_form",
    [
        pytest.param(OGONE, id=OGONE, marks=pytest.mark.tc("OF-025")),
        pytest.param(WORLDLINE, id=WORLDLINE, marks=pytest.mark.tc("OF-059")),
    ],
    indirect=True,
)
def test_uncertain_payment_registers_once_the_provider_confirms_it(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: tuple[str, str]
) -> None:
    """After an uncertain payment, the provider's webhook reports it completed: then the zaak is registered."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    reference, told = payer.pay("uncertain")
    assert told["of_payment_status"] == "processing"
    payer.confirm(reference)
    assert payer.registered()["status"]


@pytest.mark.xfail(
    strict=True,
    reason="Open Formulieren 3.5.5's ZGW registration creates the zaak when the form is completed, before the"
    " payment (pre-registration), also with wait_for_payment_to_register; the draaiboek expects no zaak",
)
@pytest.mark.parametrize("payment_form", [pytest.param(OGONE, id=OGONE)], indirect=True)
@pytest.mark.tc("OF-022")
def test_unpaid_form_leaves_no_zaak(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: tuple[str, str]
) -> None:
    """A completed form that is not paid creates no zaak, so ZAC shows none."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    assert not payer.zaak, f"zaak {payer.zaak['identificatie']} exists"


@pytest.mark.xfail(
    strict=True,
    reason="with wait_for_payment_to_register on, Open Formulieren 3.5.5 skips its payment status update"
    " (update_submission_payment_status), so the pre-registered zaak stays betalingsindicatie nog_niet after"
    " the payment; not yet reported upstream",
)
@pytest.mark.parametrize("payment_form", [pytest.param(OGONE, id=OGONE)], indirect=True)
@pytest.mark.tc("OF-024")
def test_zaak_of_a_paid_form_is_marked_paid(
    podiumd_env: Environment, openzaak: ApiClient, registry: ResourceRegistry, payment_form: tuple[str, str]
) -> None:
    """The zaak of a paid form shows it is fully paid, which ZAC displays."""
    payer = Payer(podiumd_env, openzaak, registry, payment_form)
    payer.pay("paid")
    zaak = payer.registered()
    wait_until(
        lambda: openzaak.get(str(zaak["url"]))["betalingsindicatie"] == "geheel",
        timeout=REGISTRATION_TIMEOUT,
        description=f"zaak {zaak['identificatie']} marked fully paid",
    )
