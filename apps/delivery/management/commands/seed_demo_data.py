from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.delivery.models import (
    Bazar,
    Container,
    CourierPosition,
    GlobalDeliveryConfig,
    Passage,
    Shipment,
    ShipmentStop,
)
from apps.users.models import CourierKYC, UserProfile


DEMO_PASSWORD = "demo12345"


BAZARS = [
    {
        "name": "Дордой",
        "price_from": 180,
        "price_to": 260,
        "top_left_lat": Decimal("42.946800"),
        "top_left_lon": Decimal("74.612200"),
        "bottom_right_lat": Decimal("42.928300"),
        "bottom_right_lon": Decimal("74.640200"),
        "passages": {
            "1": [
                ("101", "Текстиль", "42.941830", "74.622610"),
                ("102", "Обувь", "42.941260", "74.623210"),
                ("103", "Детские товары", "42.940740", "74.624080"),
            ],
            "5": [
                ("501", "Электроника", "42.937900", "74.626720"),
                ("502", "Аксессуары", "42.937330", "74.627460"),
            ],
            "8": [
                ("801", "Одежда", "42.934920", "74.630810"),
                ("802", "Склад выдачи", "42.934210", "74.631550"),
            ],
        },
    },
    {
        "name": "Алкан базары",
        "price_from": 160,
        "price_to": 240,
        "top_left_lat": Decimal("42.943900"),
        "top_left_lon": Decimal("74.604400"),
        "bottom_right_lat": Decimal("42.930000"),
        "bottom_right_lon": Decimal("74.616600"),
        "passages": {
            "2": [
                ("210", "Фурнитура", "42.938820", "74.609940"),
                ("211", "Бытовые товары", "42.938080", "74.610720"),
            ],
            "7": [
                ("704", "Оптовый ряд", "42.934540", "74.613120"),
                ("705", "Пункт погрузки", "42.933970", "74.613870"),
            ],
        },
    },
]


SHIPMENTS = [
    {
        "title": "DEMO Аманат: контейнеры Дордой",
        "service_type": Shipment.ServiceType.AMANAT,
        "description": "Тестовый заказ между контейнерами внутри рынка",
        "status": Shipment.Status.PENDING,
        "stops": [
            {"container": ("Дордой", "1", "101")},
            {"container": ("Дордой", "8", "802")},
        ],
    },
    {
        "title": "DEMO Тачки: маршрут 3 точки",
        "service_type": Shipment.ServiceType.CARS,
        "description": "Проверка маршрута с двумя и более точками",
        "status": Shipment.Status.ASSIGNED,
        "assign_carrier": True,
        "stops": [
            {"container": ("Алкан базары", "2", "210")},
            {"title": "ЦУМ Бишкек", "lat": "42.875210", "lon": "74.614090"},
            {"title": "Ошский рынок", "lat": "42.875720", "lon": "74.569650"},
        ],
    },
    {
        "title": "DEMO Доставка: точка А -> точка Б",
        "service_type": Shipment.ServiceType.DELIVERY,
        "description": "Тест обычной доставки из города на рынок",
        "status": Shipment.Status.IN_TRANSIT,
        "assign_carrier": True,
        "stops": [
            {"title": "Площадь Ала-Тоо", "lat": "42.876530", "lon": "74.603830"},
            {"container": ("Дордой", "5", "501")},
        ],
    },
]


class Command(BaseCommand):
    help = "Create demo bazaars, containers, users, courier position, and shipments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear-demo-shipments",
            action="store_true",
            help="Delete existing shipments with titles starting with DEMO before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        config = GlobalDeliveryConfig.get_config()
        config.base_price = Decimal("80")
        config.per_km_price = Decimal("25")
        config.min_fare = Decimal("120")
        config.save(update_fields=["base_price", "per_km_price", "min_fare", "updated_at"])

        client = self._upsert_user(
            phone="996700111222",
            first_name="Demo Client",
            role=get_user_model().Roles.CLIENT,
        )
        carrier = self._upsert_user(
            phone="996700333444",
            first_name="Demo Carrier",
            role=get_user_model().Roles.CARRIER,
        )

        CourierKYC.objects.update_or_create(
            user=carrier,
            defaults={"status": CourierKYC.Status.APPROVED},
        )
        CourierPosition.objects.update_or_create(
            user=carrier,
            defaults={"lat": Decimal("42.936900"), "lon": Decimal("74.624700")},
        )

        containers = self._seed_containers()

        if options["clear_demo_shipments"]:
            Shipment.objects.filter(is_demo=True).delete()

        created_shipments = []
        for item in SHIPMENTS:
            shipment = self._upsert_shipment(item, client, carrier, containers)
            created_shipments.append(shipment)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"Client: 996700111222 / {DEMO_PASSWORD}")
        self.stdout.write(f"Carrier: 996700333444 / {DEMO_PASSWORD}")
        self.stdout.write(f"Bazars: {Bazar.objects.count()}")
        self.stdout.write(f"Containers: {Container.objects.count()}")
        self.stdout.write(
            "Demo shipments: "
            + ", ".join(f"#{shipment.id} {shipment.service_type}" for shipment in created_shipments)
        )

    def _upsert_user(self, *, phone: str, first_name: str, role: str):
        User = get_user_model()
        user, _ = User.objects.update_or_create(
            phone_number=phone,
            defaults={
                "first_name": first_name,
                "role": role,
                "is_verify": True,
                "city": "Бишкек",
            },
        )
        user.set_password(DEMO_PASSWORD)
        user.save(update_fields=["password", "first_name", "role", "is_verify", "city"])
        UserProfile.objects.get_or_create(user=user)
        return user

    def _seed_containers(self) -> dict[tuple[str, str, str], Container]:
        out: dict[tuple[str, str, str], Container] = {}
        for bazar_item in BAZARS:
            bazar, _ = Bazar.objects.update_or_create(
                name=bazar_item["name"],
                defaults={
                    "price_from": bazar_item["price_from"],
                    "price_to": bazar_item["price_to"],
                    "top_left_lat": bazar_item["top_left_lat"],
                    "top_left_lon": bazar_item["top_left_lon"],
                    "bottom_right_lat": bazar_item["bottom_right_lat"],
                    "bottom_right_lon": bazar_item["bottom_right_lon"],
                },
            )

            for passage_number, container_items in bazar_item["passages"].items():
                passage, _ = Passage.objects.get_or_create(
                    bazar=bazar,
                    number=passage_number,
                )
                for number, title, lat, lon in container_items:
                    container, _ = Container.objects.update_or_create(
                        passage=passage,
                        number=number,
                        defaults={
                            "title": title,
                            "lat": Decimal(lat),
                            "lon": Decimal(lon),
                            "is_active": True,
                        },
                    )
                    out[(bazar.name, passage.number, container.number)] = container
        return out

    def _upsert_shipment(self, item: dict, client, carrier, containers):
        shipment, _ = Shipment.objects.update_or_create(
            title=item["title"],
            defaults={
                "client": client,
                "carrier": carrier if item.get("assign_carrier") else None,
                "service_type": item["service_type"],
                "description": item["description"],
                "is_demo": True,
                "status": item["status"],
                "is_paid": False,
            },
        )
        shipment.stops.all().delete()

        for position, stop in enumerate(item["stops"]):
            if "container" in stop:
                container = containers[stop["container"]]
                ShipmentStop.objects.create(
                    shipment=shipment,
                    position=position,
                    container=container,
                )
            else:
                ShipmentStop.objects.create(
                    shipment=shipment,
                    position=position,
                    title=stop["title"],
                    lat=Decimal(stop["lat"]),
                    lon=Decimal(stop["lon"]),
                )

        shipment.current_stop_index = 1
        shipment.estimate()
        if shipment.status == Shipment.Status.COMPLETED:
            shipment.finalize()
        shipment.save(
            update_fields=[
                "carrier",
                "service_type",
                "description",
                "status",
                "distance_km",
                "estimated_fare",
                "final_fare",
                "finished_at",
                "current_stop_index",
                "is_paid",
            ]
        )
        return shipment
