from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


def payment_amount_for_shipment(shipment) -> int:
    """Return the amount Finik must charge for this shipment."""

    test_amount = getattr(settings, "FINIK_TEST_AMOUNT", None)
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
