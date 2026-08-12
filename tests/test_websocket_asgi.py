from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from rest_framework_simplejwt.tokens import AccessToken

import pytest

from apps.delivery.models import Shipment
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
