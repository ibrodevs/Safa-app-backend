import pytest
from decimal import Decimal
from django.conf import settings
from apps.delivery.models import GlobalDeliveryConfig, Shipment, ShipmentStop
from apps.delivery.pricing import estimate_fare
from apps.delivery.geo import is_in_bishkek
from apps.users.models import User

@pytest.mark.django_db
class TestPricingLogic:
    def test_default_pricing(self):
        # Default: base 50, per_km 20, min 50
        # 2km -> 50 + 20*2 = 90
        assert estimate_fare(2) == 90
        
    def test_min_fare(self):
        # 0.1km -> 50 + 20*0.1 = 52 (which is > 50)
        # Wait, if base is 50, and per_km is 20, then even 0km is 50.
        # Let's try changing config.
        config = GlobalDeliveryConfig.get_config()
        config.base_price = 10
        config.per_km_price = 10
        config.min_fare = 50
        config.save()
        
        # 1km -> 10 + 10*1 = 20. But min is 50.
        assert estimate_fare(1) == 50
        
    def test_long_distance(self):
        config = GlobalDeliveryConfig.get_config()
        config.base_price = 50
        config.per_km_price = 20
        config.save()
        
        # 100km -> 50 + 20*100 = 2050
        assert estimate_fare(100) == 2050

@pytest.mark.django_db
class TestShipmentLogic:
    def test_shipment_estimate(self, db):
        user = User.objects.create(phone_number="996111111111", first_name="Test")
        shipment = Shipment.objects.create(client=user, title="Test Order")
        
        # Add 2 stops: Bishkek center and 1km away
        ShipmentStop.objects.create(shipment=shipment, position=0, lat=42.8714, lon=74.5880, title="Start")
        ShipmentStop.objects.create(shipment=shipment, position=1, lat=42.8814, lon=74.5880, title="End")
        
        fare = shipment.estimate()
        assert fare > 0
        assert shipment.distance_km > 0
        
    def test_empty_route_estimate(self, db):
        user = User.objects.create(phone_number="996222222222", first_name="Test")
        shipment = Shipment.objects.create(client=user, title="Empty Order")
        
        # No stops
        fare = shipment.estimate()
        # Should be base_price or min_fare since distance is 0
        config = GlobalDeliveryConfig.get_config()
        assert fare == int(config.min_fare)

@pytest.mark.django_db
class TestGeoLogic:
    def test_bishkek_radius(self):
        # Center: 42.8714, 74.5880
        # Inside (center)
        assert is_in_bishkek(42.8714, 74.5880) is True
        # Inside (edge - ~5km away)
        assert is_in_bishkek(42.8314, 74.5880) is True
        # Outside (~50km away)
        assert is_in_bishkek(42.4714, 74.5880) is False
