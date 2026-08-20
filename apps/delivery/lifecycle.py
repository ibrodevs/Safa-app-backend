from django.utils import timezone

from apps.payments.amounts import effective_finik_test_amount

from .models import Shipment


class ShipmentFareUnavailable(ValueError):
    pass


def mark_shipment_awaiting_payment(shipment: Shipment) -> Shipment:
    """Freeze the fare after the carrier finishes, without completing payment."""

    if shipment.status == Shipment.Status.AWAITING_PAYMENT:
        return shipment
    if shipment.status not in (
        Shipment.Status.ASSIGNED,
        Shipment.Status.IN_TRANSIT,
    ):
        raise ValueError("shipment_cannot_await_payment")
    if not shipment.carrier_id:
        raise ValueError("shipment_has_no_carrier")

    fare = int(shipment.final_fare or shipment.estimated_fare or 0)
    if fare <= 0:
        # Старые/тестовые заказы могли быть созданы с нулевой ценой. В режиме
        # фиксированной тестовой суммы это валидный платёж и завершение работы
        # не должно падать с HTTP 500.
        test_amount = effective_finik_test_amount()
        if test_amount is not None:
            fare = int(test_amount)
        else:
            fare = int(shipment.estimate() or 0)
    if fare <= 0:
        raise ShipmentFareUnavailable("shipment_has_no_final_fare")

    shipment.final_fare = fare
    shipment.status = Shipment.Status.AWAITING_PAYMENT
    shipment.work_completed_at = shipment.work_completed_at or timezone.now()
    shipment.save(
        update_fields=["status", "final_fare", "work_completed_at"]
    )
    return shipment
