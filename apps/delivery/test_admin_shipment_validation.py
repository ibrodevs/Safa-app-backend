import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.delivery.models import Shipment
from apps.users.models import User


@pytest.mark.django_db
def test_unpaid_shipment_completion_is_rejected_before_database_save():
    client = User.objects.create_user(
        phone_number="996700940001",
        password="secret123",
        first_name="Client",
        is_verify=True,
    )
    shipment = Shipment(
        client=client,
        title="Unpaid admin order",
        status=Shipment.Status.COMPLETED,
        is_paid=False,
    )

    with pytest.raises(ValidationError) as error:
        shipment.full_clean()

    assert "status" in error.value.message_dict
    assert "Нельзя завершить неоплаченный заказ" in error.value.message_dict["status"][0]


@pytest.mark.django_db
def test_admin_shows_validation_error_instead_of_http_500(admin_client):
    client = User.objects.create_user(
        phone_number="996700940002",
        password="secret123",
        first_name="Client",
        is_verify=True,
    )
    shipment = Shipment.objects.create(
        client=client,
        title="Unpaid admin order",
        status=Shipment.Status.PENDING,
        is_paid=False,
    )

    response = admin_client.post(
        reverse("admin:delivery_shipment_change", args=[shipment.pk]),
        {
            "title": shipment.title,
            "service_type": Shipment.ServiceType.DELIVERY,
            "description": "",
            "client": str(client.pk),
            "carrier": "",
            "status": Shipment.Status.COMPLETED,
            "stops-TOTAL_FORMS": "0",
            "stops-INITIAL_FORMS": "0",
            "stops-MIN_NUM_FORMS": "0",
            "stops-MAX_NUM_FORMS": "1000",
            "_save": "Сохранить",
        },
    )

    assert response.status_code == 200
    assert "Нельзя завершить неоплаченный заказ" in response.content.decode()
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.PENDING


@pytest.mark.django_db
def test_admin_can_mark_order_paid_and_change_status_to_completed(admin_client):
    client = User.objects.create_user(
        phone_number="996700940003",
        password="secret123",
        first_name="Client",
        is_verify=True,
    )
    shipment = Shipment.objects.create(
        client=client,
        title="Manual admin completion",
        status=Shipment.Status.PENDING,
        is_paid=False,
    )

    response = admin_client.post(
        reverse("admin:delivery_shipment_change", args=[shipment.pk]),
        {
            "title": shipment.title,
            "service_type": Shipment.ServiceType.DELIVERY,
            "description": "",
            "client": str(client.pk),
            "carrier": "",
            "status": Shipment.Status.COMPLETED,
            "is_paid": "on",
            "stops-TOTAL_FORMS": "0",
            "stops-INITIAL_FORMS": "0",
            "stops-MIN_NUM_FORMS": "0",
            "stops-MAX_NUM_FORMS": "1000",
            "_save": "Сохранить",
        },
    )

    assert response.status_code == 302
    shipment.refresh_from_db()
    assert shipment.status == Shipment.Status.COMPLETED
    assert shipment.is_paid is True
    assert shipment.paid_at is not None
    assert shipment.work_completed_at is not None
    assert shipment.finished_at is not None
