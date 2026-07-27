import pytest
from django.core.management import call_command

from apps.delivery.models import Bazar, Container, Shipment


@pytest.mark.django_db
def test_seed_demo_data_creates_containers_and_shipments():
    call_command("seed_demo_data", "--clear-demo-shipments", verbosity=0)
    call_command("seed_demo_data", verbosity=0)

    assert Bazar.objects.filter(name="Дордой").exists()
    assert Container.objects.filter(is_active=True).count() == 11
    assert Shipment.objects.filter(title__startswith="DEMO ").count() == 3
    assert set(
        Shipment.objects.filter(title__startswith="DEMO ").values_list(
            "service_type",
            flat=True,
        )
    ) == {
        Shipment.ServiceType.AMANAT,
        Shipment.ServiceType.CARS,
        Shipment.ServiceType.DELIVERY,
    }
