from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.delivery.models import Bazar, Shipment, ShipmentStop
from apps.notification.admin import RoleBroadcastAdmin
from apps.notification.events import (
    broadcast_to_role,
    notify_shipment_offer_for_carrier,
    notify_shipment_status,
)
from apps.notification.fcm_client import FCMSendResult, _build_message
from apps.notification.models import FCMToken, Notification, RoleBroadcast
from apps.users.models import User


def _user(
    phone: str,
    *,
    role: str = User.Roles.CLIENT,
    specialist_type: str | None = None,
    is_active: bool = True,
) -> User:
    return User.objects.create_user(
        phone_number=phone,
        password="pass12345",
        first_name="Push",
        role=role,
        specialist_type=specialist_type,
        is_verify=True,
        is_active=is_active,
    )


def _token(user: User, suffix: str) -> FCMToken:
    return FCMToken.objects.create(
        user=user,
        token=f"notification-test-token-{suffix}",
        platform=FCMToken.Platform.ANDROID,
    )


def _bazar() -> Bazar:
    return Bazar.objects.create(
        name="Push bazar",
        top_left_lat=42.90,
        top_left_lon=74.58,
        bottom_right_lat=42.85,
        bottom_right_lon=74.64,
        price_from=100,
    )


def _shipment(client: User, *, service_type: str) -> Shipment:
    shipment = Shipment.objects.create(
        client=client,
        title="Тестовый заказ",
        service_type=service_type,
        status=Shipment.Status.PENDING,
        estimated_fare=200,
    )
    ShipmentStop.objects.create(
        shipment=shipment,
        position=0,
        title="A",
        lat=42.87,
        lon=74.60,
    )
    ShipmentStop.objects.create(
        shipment=shipment,
        position=1,
        title="B",
        lat=42.88,
        lon=74.61,
    )
    return shipment


@pytest.mark.django_db
def test_cart_offer_is_sent_only_to_cart_specialists():
    _bazar()
    client = _user("996700881001")
    cart = _user(
        "996700881002",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.CART,
    )
    delivery = _user(
        "996700881003",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    _token(client, "client")
    _token(cart, "cart")
    _token(delivery, "delivery")
    shipment = _shipment(client, service_type=Shipment.ServiceType.CARS)

    with patch(
        "apps.notification.events.send_data_message",
        return_value=FCMSendResult(success=True),
    ):
        notify_shipment_offer_for_carrier(shipment)

    recipients = set(
        Notification.objects.filter(type="shipment_offer").values_list(
            "user_id", flat=True
        )
    )
    assert recipients == {cart.id}


@pytest.mark.django_db
def test_delivery_offer_is_sent_only_to_delivery_specialists():
    _bazar()
    client = _user("996700881011")
    cart = _user(
        "996700881012",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.CART,
    )
    delivery = _user(
        "996700881013",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    _token(cart, "cart-delivery-test")
    _token(delivery, "delivery-delivery-test")
    shipment = _shipment(client, service_type=Shipment.ServiceType.DELIVERY)

    with patch(
        "apps.notification.events.send_data_message",
        return_value=FCMSendResult(success=True),
    ):
        notify_shipment_offer_for_carrier(shipment)

    recipients = set(
        Notification.objects.filter(type="shipment_offer").values_list(
            "user_id", flat=True
        )
    )
    assert recipients == {delivery.id}


@pytest.mark.django_db
def test_status_update_goes_to_client_and_assigned_carrier_only():
    client = _user("996700881021")
    assigned = _user(
        "996700881022",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    unrelated = _user(
        "996700881023",
        role=User.Roles.CARRIER,
        specialist_type=User.SpecialistType.DELIVERY,
    )
    _token(client, "status-client")
    _token(assigned, "status-assigned")
    _token(unrelated, "status-unrelated")
    shipment = _shipment(client, service_type=Shipment.ServiceType.DELIVERY)
    shipment.carrier = assigned
    shipment.status = Shipment.Status.ASSIGNED
    shipment.save(update_fields=["carrier", "status"])

    with patch(
        "apps.notification.events.send_data_message",
        return_value=FCMSendResult(success=True),
    ):
        notify_shipment_status(shipment)

    notifications = Notification.objects.filter(type="shipment_status")
    assert set(notifications.values_list("user_id", flat=True)) == {
        client.id,
        assigned.id,
    }
    assert notifications.get(user=client).data["app"] == "client"
    assert notifications.get(user=assigned).data["app"] == "carrier"


@pytest.mark.django_db
def test_manual_role_broadcast_skips_inactive_users_and_counts_fcm_acceptance():
    active = _user("996700881031")
    inactive = _user("996700881032", is_active=False)
    _token(active, "broadcast-active")
    _token(inactive, "broadcast-inactive")

    with patch(
        "apps.notification.events.send_data_message",
        return_value=FCMSendResult(success=True),
    ):
        count = broadcast_to_role(
            role=User.Roles.CLIENT,
            app="client",
            title="Системное",
            body="Тест",
        )

    assert count == 1
    assert Notification.objects.filter(user=active).count() == 1
    assert Notification.objects.filter(user=inactive).count() == 0


@pytest.mark.django_db
def test_dead_fcm_token_is_deactivated_and_not_counted_as_delivered():
    client = _user("996700881041")
    token = _token(client, "dead")

    with patch(
        "apps.notification.events.send_data_message",
        return_value=FCMSendResult(
            success=False,
            deactivate_token=True,
            error="UNREGISTERED",
        ),
    ):
        count = broadcast_to_role(
            role=User.Roles.CLIENT,
            app="client",
            title="Системное",
            body="Тест",
        )

    token.refresh_from_db()
    assert token.is_active is False
    assert count == 0


def test_role_broadcast_rejects_cross_app_delivery():
    broadcast = RoleBroadcast(
        title="Wrong app",
        body="",
        role=User.Roles.CLIENT,
        app="carrier",
    )
    with pytest.raises(ValidationError):
        broadcast.full_clean()


@pytest.mark.django_db
def test_editing_sent_broadcast_does_not_send_it_again():
    obj = RoleBroadcast.objects.create(
        title="Already sent",
        body="Body",
        role=User.Roles.CLIENT,
        app="client",
        sent_at=timezone.now(),
        sent_count=1,
    )
    model_admin = RoleBroadcastAdmin(RoleBroadcast, admin.site)

    with patch("apps.notification.admin.broadcast_to_role") as mocked_send:
        model_admin.save_model(SimpleNamespace(), obj, form=None, change=True)

    mocked_send.assert_not_called()


def test_visible_fcm_message_contains_os_notification_payload():
    message = _build_message(
        token="token",
        data={
            "title": "Заказ",
            "body": "Назначен специалист",
            "silent": "0",
        },
        ttl="60s",
        collapse_key="shipment_1",
    )["message"]

    assert message["notification"]["title"] == "Заказ"
    assert message["android"]["notification"]["channel_id"] == "dogo_main"
    assert message["apns"]["headers"]["apns-push-type"] == "alert"


def test_silent_fcm_message_stays_data_only():
    message = _build_message(
        token="token",
        data={"silent": "1", "type": "sync"},
        ttl="60s",
        collapse_key=None,
    )["message"]

    assert "notification" not in message
    assert message["apns"]["headers"]["apns-push-type"] == "background"
    assert message["apns"]["headers"]["apns-priority"] == "5"
