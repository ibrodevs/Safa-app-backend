import pytest
from rest_framework.test import APIClient

from apps.delivery.models import Bazar, Shipment, ShipmentStop
from apps.users.models import User


def _user(phone: str, role: str = User.Roles.CLIENT, specialist_type: str | None = None) -> User:
    return User.objects.create_user(
        phone_number=phone,
        password="pass12345",
        first_name="User",
        role=role,
        specialist_type=specialist_type,
        is_verify=True,
    )


def _bazar() -> Bazar:
    return Bazar.objects.get_or_create(
        name="Тестовый базар",
        defaults={
            "top_left_lat": 42.90,
            "top_left_lon": 74.58,
            "bottom_right_lat": 42.85,
            "bottom_right_lon": 74.64,
            "price_from": 100,
        },
    )[0]


def _shipment(client: User, title: str, status: str = Shipment.Status.PENDING) -> Shipment:
    shipment = Shipment.objects.create(
        client=client,
        title=title,
        status=status,
        service_type=Shipment.ServiceType.DELIVERY,
    )
    ShipmentStop.objects.create(shipment=shipment, position=0, title="A", lat=42.87, lon=74.60)
    ShipmentStop.objects.create(shipment=shipment, position=1, title="B", lat=42.88, lon=74.61)
    return shipment


@pytest.mark.django_db
def test_client_list_does_not_show_demo_shipments():
    user = _user("996700555201")
    _shipment(user, "DEMO Доставка: точка А -> точка Б")
    visible = _shipment(user, "Настоящий заказ")

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get("/api/delivery/shipments/")

    assert response.status_code == 200
    ids = {item["id"] for item in response.data["results"]}
    assert visible.id in ids
    assert Shipment.objects.get(title__startswith="DEMO ").id not in ids


@pytest.mark.django_db
def test_nearby_does_not_show_demo_shipments_to_carrier():
    _bazar()
    order_client = _user("996700555202")
    carrier = _user("996700555203", role=User.Roles.CARRIER, specialist_type=User.SpecialistType.DELIVERY)
    _shipment(order_client, "DEMO Аманат: контейнеры Дордой")
    visible = _shipment(order_client, "Реальный свободный заказ")

    client = APIClient()
    client.force_authenticate(user=carrier)
    response = client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.60")

    assert response.status_code == 200
    ids = {item["id"] for item in response.data["results"]}
    assert visible.id in ids
    assert Shipment.objects.get(title__startswith="DEMO ").id not in ids


@pytest.mark.django_db
def test_cars_shipment_accepts_long_route():
    _bazar()
    user = _user("996700555204")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/delivery/shipments/",
        {
            "title": "Маршрут тачки",
            "service_type": Shipment.ServiceType.CARS,
            "stops": [
                {"title": f"Точка {i}", "lat": 42.87 + i * 0.001, "lon": 74.60 + i * 0.001}
                for i in range(30)
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert Shipment.objects.get(id=response.data["id"]).stops.count() == 30
