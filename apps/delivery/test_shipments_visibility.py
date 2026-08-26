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
        is_demo=title.startswith("DEMO "),
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "service_type,phone",
    [
        (Shipment.ServiceType.DELIVERY, "996700555221"),
        (Shipment.ServiceType.CARS, "996700555222"),
    ],
)
def test_address_services_can_create_route_outside_bazar(service_type, phone):
    user = _user(phone)
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        "/api/delivery/shipments/",
        {
            "title": "Городской адресный маршрут",
            "service_type": service_type,
            "stops": [
                {"title": "Улица А", "lat": 43.40, "lon": 75.90},
                {"title": "Улица Б", "lat": 43.41, "lon": 75.91},
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["service_type"] == service_type


@pytest.mark.django_db
def test_nearby_shows_free_order_to_every_specialist_type():
    """Лента специалиста не должна фильтровать заказ по типу специализации."""

    _bazar()
    order_client = _user("996700555210")
    cart_carrier = _user(
        "996700555211",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.CART,
    )
    delivery = _shipment(order_client, "Доставка для любого специалиста")

    client = APIClient()
    client.force_authenticate(user=cart_carrier)
    response = client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.60")

    assert response.status_code == 200
    assert delivery.id in {item["id"] for item in response.data["results"]}


@pytest.mark.django_db
def test_nearby_shows_order_with_stops_outside_any_bazar():
    """Точка вне границ базара больше не прячет заказ из ленты."""

    order_client = _user("996700555212")
    carrier = _user(
        "996700555213",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    shipment = Shipment.objects.create(
        client=order_client,
        title="Заказ вне базара",
        status=Shipment.Status.PENDING,
        service_type=Shipment.ServiceType.DELIVERY,
    )
    ShipmentStop.objects.create(shipment=shipment, position=0, title="A", lat=43.40, lon=75.90)
    ShipmentStop.objects.create(shipment=shipment, position=1, title="B", lat=43.41, lon=75.91)

    client = APIClient()
    client.force_authenticate(user=carrier)
    response = client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.60")

    assert response.status_code == 200
    assert shipment.id in {item["id"] for item in response.data["results"]}


@pytest.mark.django_db
def test_nearby_hides_taken_and_own_orders():
    _bazar()
    order_client = _user("996700555214")
    carrier = _user(
        "996700555215",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    other_carrier = _user(
        "996700555216",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    free = _shipment(order_client, "Свободный заказ")
    taken = _shipment(order_client, "Уже занятый заказ")
    taken.carrier = other_carrier
    taken.status = Shipment.Status.ASSIGNED
    taken.save(update_fields=["carrier", "status"])
    own = _shipment(carrier, "Собственный заказ специалиста")

    client = APIClient()
    client.force_authenticate(user=carrier)
    response = client.get("/api/delivery/shipments/nearby/?lat=42.87&lon=74.60")

    assert response.status_code == 200
    ids = {item["id"] for item in response.data["results"]}
    assert free.id in ids
    assert taken.id not in ids
    assert own.id not in ids


@pytest.mark.django_db
def test_specialist_can_accept_order_of_another_service_type():
    """Карточка видна — значит и кнопка «Принять» не должна отвечать 403."""

    _bazar()
    order_client = _user("996700555217")
    cart_carrier = _user(
        "996700555218",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.CART,
    )
    shipment = _shipment(order_client, "Доставка, которую берёт тележечник")

    client = APIClient()
    client.force_authenticate(user=cart_carrier)
    response = client.post(f"/api/delivery/shipments/{shipment.id}/accept/")

    assert response.status_code == 200
    shipment.refresh_from_db()
    assert shipment.carrier_id == cart_carrier.id
    assert shipment.status == Shipment.Status.ASSIGNED


@pytest.mark.django_db
def test_accept_is_idempotent_for_the_assigned_specialist():
    order_client = _user("996700555219")
    carrier = _user(
        "996700555220",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    shipment = _shipment(order_client, "Повторное принятие")

    client = APIClient()
    client.force_authenticate(user=carrier)
    first = client.post(f"/api/delivery/shipments/{shipment.id}/accept/")
    second = client.post(f"/api/delivery/shipments/{shipment.id}/accept/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.data["carrier_id"] == carrier.id
    assert second.data["status"] == Shipment.Status.ASSIGNED
