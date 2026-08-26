from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


def effective_safa_test_price() -> int | None:
    """Return the global API/Finik test price when explicitly enabled."""

    if bool(getattr(settings, "SAFA_TEST_PRICING", False)):
        return int(getattr(settings, "SAFA_TEST_PRICE", 1))
    return None


def effective_finik_test_amount() -> int | None:
    safa_test_price = effective_safa_test_price()
    if safa_test_price is not None:
        return safa_test_price

    test_amount = getattr(settings, "FINIK_TEST_AMOUNT", None)
    if test_amount is None:
        return None
    allowed = (
        bool(getattr(settings, "DEBUG", False))
        or bool(getattr(settings, "FINIK_BETA", False))
        or bool(getattr(settings, "FINIK_ALLOW_TEST_AMOUNT", False))
    )
    return int(test_amount) if allowed else None


def payment_amount_for_shipment(shipment) -> int:
    """Return the amount Finik must charge for this shipment."""

    test_amount = effective_finik_test_amount()
    if test_amount is not None:
        return int(test_amount)
    return int(shipment.final_fare or shipment.estimated_fare or 0)


def commission_for_payment_amount(amount: int) -> int:
    pct = getattr(settings, "PLATFORM_COMMISSION_PCT", Decimal("0"))
    value = (Decimal(amount) * pct).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(value)


def carrier_income_for_shipment(shipment) -> int:
    amount = payment_amount_for_shipment(shipment)
    return amount - commission_for_payment_amount(amount)
