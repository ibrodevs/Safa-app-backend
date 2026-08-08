import pytest

from apps.delivery.serializer import ShipmentDetailSerializer, ShipmentNearbySerializer
from apps.delivery.models import Shipment, ShipmentStop
from apps.users.models import User


@pytest.mark.django_db
def test_nearby_payload_exposes_same_price_fields_as_detail():
    user = User.objects.create(phone_number='996555123456', first_name='Client')
    shipment = Shipment.objects.create(
        client=user,
        title='Заказ',
        service_type=Shipment.ServiceType.DELIVERY,
        estimated_fare=320,
        final_fare=350,
    )
    ShipmentStop.objects.create(
        shipment=shipment,
        position=0,
        title='A',
        lat='42.870000',
        lon='74.600000',
    )

    detail = ShipmentDetailSerializer(shipment).data
    nearby = ShipmentNearbySerializer(
        shipment,
        context={'user_lat': 42.87, 'user_lon': 74.60},
    ).data

    assert nearby['service_type'] == detail['service_type']
    assert nearby['estimated_fare'] == detail['estimated_fare'] == 320
    assert nearby['final_fare'] == detail['final_fare'] == 350
    assert nearby['commission'] == detail['commission']
    assert nearby['courier_income'] == detail['courier_income']
    assert nearby['stops_count'] == detail['stops_count'] == 1
