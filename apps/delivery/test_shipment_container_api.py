import pytest
from rest_framework.test import APIClient

from apps.delivery.models import Bazar, Container, Passage, Shipment
from apps.users.models import User


@pytest.mark.django_db
def test_create_shipment_with_existing_container_does_not_fail_logging():
    user = User.objects.create_user(
        phone_number="996701222333",
        password="demo12345",
        first_name="Container API",
        is_verify=True,
    )
    bazar = Bazar.objects.create(name="Дордой", price_from=180)
    passage = Passage.objects.create(bazar=bazar, number="1")
    Container.objects.create(
        passage=passage,
        number="101",
        title="Текстиль",
        lat="42.941830",
        lon="74.622610",
    )

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.post(
        "/api/delivery/shipments/",
        {
            "title": "Container order",
            "service_type": Shipment.ServiceType.DELIVERY,
            "stops": [
                {"title": "Площадь Ала-Тоо", "lat": 42.876530, "lon": 74.603830},
                {"bazar": "Дордой", "passage": "1", "container": "101"},
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    shipment = Shipment.objects.get(id=response.data["id"])
    assert shipment.stops.count() == 2
    assert shipment.stops.order_by("position").last().container.number == "101"
