import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.delivery.models import Shipment
from apps.users.models import User


def _users():
    client = User.objects.create_user(
        phone_number="996701111111",
        password="secret123",
        first_name="Client",
        role=User.Roles.CLIENT,
    )
    carrier = User.objects.create_user(
        phone_number="996702222222",
        password="secret123",
        first_name="Carrier",
        role=User.Roles.CARRIER,
    )
    return client, carrier


@pytest.mark.django_db
def test_carrier_finishing_work_waits_for_client_payment():
    client_user, carrier = _users()
    shipment = Shipment.objects.create(
        client=client_user,
        carrier=carrier,
        title="Delivery",
        estimated_fare=500,
        status=Shipment.Status.IN_TRANSIT,
    )
    api = APIClient()
    api.force_authenticate(carrier)

    response = api.post(f"/api/delivery/shipments/{shipment.id}/advance/")

    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.AWAITING_PAYMENT
    assert shipment.final_fare == 500
    assert shipment.work_completed_at is not None
    assert shipment.finished_at is None
    assert shipment.is_paid is False


@pytest.mark.django_db
def test_carrier_cannot_force_completed_status_before_payment():
    client_user, carrier = _users()
    shipment = Shipment.objects.create(
        client=client_user,
        carrier=carrier,
        title="Delivery",
        estimated_fare=500,
        status=Shipment.Status.IN_TRANSIT,
    )
    api = APIClient()
    api.force_authenticate(carrier)

    response = api.post(
        f"/api/delivery/shipments/{shipment.id}/set_status/",
        {"status": Shipment.Status.COMPLETED},
        format="json",
    )

    assert response.status_code == 409
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.IN_TRANSIT


@pytest.mark.django_db
@override_settings(FINIK_ACCOUNT_ID="account", FINIK_API_KEY="key")
def test_client_cannot_start_payment_before_work_is_finished():
    client_user, carrier = _users()
    shipment = Shipment.objects.create(
        client=client_user,
        carrier=carrier,
        title="Delivery",
        estimated_fare=500,
        status=Shipment.Status.IN_TRANSIT,
    )
    api = APIClient()
    api.force_authenticate(client_user)

    response = api.post(f"/api/delivery/shipments/{shipment.id}/pay/finik/")

    assert response.status_code == 409
    assert response.data["detail"] == "payment_not_due"


@pytest.mark.django_db
def test_awaiting_payment_timestamp_is_stable():
    client_user, carrier = _users()
    completed_at = timezone.now()
    shipment = Shipment.objects.create(
        client=client_user,
        carrier=carrier,
        title="Delivery",
        estimated_fare=500,
        final_fare=500,
        status=Shipment.Status.AWAITING_PAYMENT,
        work_completed_at=completed_at,
    )

    assert shipment.work_completed_at == completed_at


@pytest.mark.django_db
def test_client_cannot_cancel_after_work_is_finished():
    client_user, carrier = _users()
    shipment = Shipment.objects.create(
        client=client_user,
        carrier=carrier,
        title="Delivery",
        estimated_fare=500,
        final_fare=500,
        status=Shipment.Status.AWAITING_PAYMENT,
        work_completed_at=timezone.now(),
    )
    api = APIClient()
    api.force_authenticate(client_user)

    response = api.delete(f"/api/delivery/shipments/{shipment.id}/")

    assert response.status_code == 409
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.AWAITING_PAYMENT


@pytest.mark.django_db
def test_database_rejects_completed_unpaid_shipment():
    client_user, carrier = _users()
    shipment = Shipment.objects.create(
        client=client_user,
        carrier=carrier,
        title="Delivery",
        estimated_fare=500,
        status=Shipment.Status.IN_TRANSIT,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Shipment.objects.filter(pk=shipment.pk).update(
            status=Shipment.Status.COMPLETED,
            is_paid=False,
        )
