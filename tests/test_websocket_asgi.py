from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

import pytest

from apps.delivery.models import CourierPosition, Shipment
from apps.users.models import User
from core.asgi import application


def _user(phone: str) -> User:
    return User.objects.create_user(
        phone_number=phone,
        password="test-password",
        first_name="WebSocket",
        is_verify=True,
    )


@pytest.mark.django_db(transaction=True)
def test_shipment_websocket_uses_jwt_and_asgi_routing():
    client = _user("996700990001")
    outsider = _user("996700990002")
    shipment = Shipment.objects.create(client=client, title="WebSocket order")

    async def scenario():
        token = str(AccessToken.for_user(client))
        communicator = WebsocketCommunicator(
            application,
            f"/ws/shipments/{shipment.id}/?token={token}",
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "ping"})
        assert await communicator.receive_json_from() == {"type": "pong"}
        await communicator.disconnect()

        outsider_token = str(AccessToken.for_user(outsider))
        rejected = WebsocketCommunicator(
            application,
            f"/ws/shipments/{shipment.id}/?token={outsider_token}",
        )
        outsider_connected, _ = await rejected.connect()
        assert outsider_connected is False

    async_to_sync(scenario)()


@pytest.mark.django_db(transaction=True)
def test_client_receives_initial_and_live_courier_position():
    client = _user("996700990003")
    carrier = _user("996700990004")
    carrier.role = User.Roles.CARRIER
    carrier.is_active = True
    carrier.save(update_fields=["role", "is_active"])
    shipment = Shipment.objects.create(
        client=client,
        carrier=carrier,
        title="Tracked order",
        status=Shipment.Status.ASSIGNED,
    )
    CourierPosition.objects.create(user=carrier, lat="42.870000", lon="74.600000")

    def post_position():
        api = APIClient()
        api.force_authenticate(carrier)
        return api.post(
            "/api/delivery/position/",
            {"lat": 42.871, "lon": 74.601},
            format="json",
        ).status_code

    async def scenario():
        token = str(AccessToken.for_user(client))
        communicator = WebsocketCommunicator(
            application,
            f"/ws/shipments/{shipment.id}/?token={token}",
        )
        connected, _ = await communicator.connect()
        assert connected is True

        initial = await communicator.receive_json_from()
        assert initial["type"] == "telemetry"
        assert initial["courier"]["lat"] == "42.870000"
        assert initial["courier"]["lon"] == "74.600000"

        assert await database_sync_to_async(post_position)() == 200
        update = await communicator.receive_json_from()
        assert update["type"] == "telemetry"
        assert update["shipment_id"] == shipment.id
        assert update["courier"]["lat"] == "42.871000"
        assert update["courier"]["lon"] == "74.601000"
        assert update["courier"]["updated_at"]
        await communicator.disconnect()

    async_to_sync(scenario)()
