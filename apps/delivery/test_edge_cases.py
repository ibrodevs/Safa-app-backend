import pytest
from decimal import Decimal
from apps.delivery.models import Shipment, ShipmentStop, GlobalDeliveryConfig
from apps.users.models import User

@pytest.mark.django_db
class TestEdgeCases:
    def test_return_to_start_calculation(self, client):
        user = User.objects.create(phone_number="996333333333", first_name="RTS")
        shipment = Shipment.objects.create(client=user, title="RTS Order")
        
        # Triangle route: A -> B -> A
        # A: (42.87, 74.58)
        # B: (42.88, 74.58) (~1.1 km away)
        # Total should be ~2.2 km
        ShipmentStop.objects.create(shipment=shipment, position=0, lat=42.87, lon=74.58, title="A")
        ShipmentStop.objects.create(shipment=shipment, position=1, lat=42.88, lon=74.58, title="B")
        ShipmentStop.objects.create(shipment=shipment, position=2, lat=42.87, lon=74.58, title="A back")
        
        fare = shipment.estimate()
        # 50 + 20*2.22 = ~94.4
        assert 90 <= fare <= 100
        assert shipment.distance_km > 2.0

    def test_invalid_coordinates_handling(self, db):
        user = User.objects.create(phone_number="996444444444", first_name="BadCoords")
        shipment = Shipment.objects.create(client=user, title="Bad Order")
        
        # Stop without coordinates
        ShipmentStop.objects.create(shipment=shipment, position=0, lat=None, lon=None, title="Nowhere")
        
        fare = shipment.estimate()
        # Should default to min_fare if points are missing
        config = GlobalDeliveryConfig.get_config()
        assert fare == int(config.min_fare)

    def test_config_update_immediate_effect(self, db):
        user = User.objects.create(phone_number="996555555555", first_name="ConfigTest")
        shipment = Shipment.objects.create(client=user, title="Price Change Test")
        ShipmentStop.objects.create(shipment=shipment, position=0, lat=42.87, lon=74.58)
        ShipmentStop.objects.create(shipment=shipment, position=1, lat=42.90, lon=74.58) # ~3.3km
        
        # Initial estimate (base 50, km 20) -> 50 + 20*3.3 = 116
        fare1 = shipment.estimate()
        
        # Update config to base 1000
        config = GlobalDeliveryConfig.get_config()
        config.base_price = 1000
        config.save()
        
        fare2 = shipment.estimate()
        assert fare2 > 1000
        assert fare2 != fare1

    def test_extreme_high_pricing(self, db):
        # Verification that Decimal handles large numbers
        config = GlobalDeliveryConfig.get_config()
        config.base_price = 999999
        config.save()
        
        user = User.objects.create(phone_number="996666666666", first_name="Rich")
        shipment = Shipment.objects.create(client=user)
        ShipmentStop.objects.create(shipment=shipment, position=0, lat=40, lon=70)
        ShipmentStop.objects.create(shipment=shipment, position=1, lat=41, lon=71)
        
        fare = shipment.estimate()
        assert fare >= 999999
