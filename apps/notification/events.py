from __future__ import annotations

import logging
import uuid
from typing import Any, Iterable

from django.utils import timezone

from apps.delivery.specialists import shipment_matches_specialist
from apps.users.models import User
from .fcm_client import send_data_message
from .models import FCMToken, Notification

logger = logging.getLogger(__name__)


def _base_data(
    *,
    app: str,
    type_: str,
    title: str,
    body: str,
    channel: str,
    deep_link: str,
    silent: bool = False,
) -> dict:
    return {
        "app": app,
        "type": type_,
        "event_id": uuid.uuid4().hex,
        "sent_at": timezone.now().isoformat(),
        "title": title,
        "body": body,
        "channel": channel,
        "deep_link": deep_link,
        "silent": "1" if silent else "0",
    }


def _log_notification(user_id: int, data: dict[str, Any]) -> None:
    try:
        Notification.objects.create(
            user_id=user_id,
            type=data.get("type") or "system",
            channel=data.get("channel") or Notification.Channel.SYSTEM,
            title=data.get("title") or "",
            body=data.get("body") or "",
            data=dict(data),
            event_id=data.get("event_id") or "",
        )
    except Exception as exc:
        logger.exception("notification_log_error user=%s: %s", user_id, exc)


def _send_to_user(
    user_id: int | None,
    data: dict,
    *,
    ttl: str = "300s",
    collapse_key: str | None = None,
) -> bool:
    """Persist the in-app notification and try every active device token.

    Returns True when Firebase accepted the push for at least one device. A push
    failure never raises into shipment creation/status transitions.
    """

    if not user_id:
        return False

    _log_notification(user_id, data)

    tokens: Iterable[FCMToken] = list(
        FCMToken.objects.filter(user_id=user_id, is_active=True)
    )
    delivered = False
    for token_obj in tokens:
        result = send_data_message(
            token=token_obj.token,
            data=data,
            ttl=ttl,
            collapse_key=collapse_key,
            platform=token_obj.platform,
        )
        delivered = delivered or result.success
        if result.deactivate_token:
            FCMToken.objects.filter(pk=token_obj.pk, is_active=True).update(
                is_active=False,
            )
    return delivered


def notify_shipment_offer_for_carrier(shipment) -> None:
    stops = list(shipment.stops.order_by("position"))
    pickup = stops[0] if stops else None
    dropoff = stops[-1] if len(stops) > 1 else pickup

    title = "Новая доставка рядом"
    body = f"{shipment.title} · {shipment.estimated_fare} сом"

    base = _base_data(
        app="carrier",
        type_="shipment_offer",
        title=title,
        body=body,
        channel="orders",
        deep_link=f"app://carrier/shipment/{shipment.id}/offer",
    )

    extra = {
        "shipment_id": str(shipment.id),
        "public_code": shipment.public_code,
        "service_type": shipment.service_type,
        "estimated_fare": str(shipment.estimated_fare),
        "pickup_title": pickup.title if pickup else "",
        "pickup_lat": str(pickup.lat) if pickup else "",
        "pickup_lon": str(pickup.lon) if pickup else "",
        "dropoff_title": dropoff.title if dropoff else "",
        "dropoff_lat": str(dropoff.lat) if dropoff else "",
        "dropoff_lon": str(dropoff.lon) if dropoff else "",
    }

    data = {**base, **extra}
    collapse_key = f"shipment_offer_{shipment.id}"

    # Push visibility must match the actual order-feed eligibility. Previously
    # every carrier with a token received every offer, including a cart
    # specialist receiving courier-only jobs (and vice versa).
    carrier_ids = (
        FCMToken.objects.filter(
            user__role=User.Roles.CARRIER,
            user__is_active=True,
            is_active=True,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )
    carriers = User.objects.filter(
        id__in=carrier_ids,
        role=User.Roles.CARRIER,
        is_active=True,
    )
    for carrier in carriers:
        if carrier.id == shipment.client_id:
            continue
        if not shipment_matches_specialist(shipment, carrier):
            continue
        _send_to_user(
            carrier.id,
            dict(data),
            ttl="120s",
            collapse_key=collapse_key,
        )


def notify_shipment_status(shipment) -> None:
    status = shipment.status

    title_map = {
        shipment.Status.PENDING: "Новая заявка создана",
        shipment.Status.ASSIGNED: "Курьер назначен",
        shipment.Status.IN_TRANSIT: "Посылка в пути",
        shipment.Status.AWAITING_PAYMENT: "Ожидается оплата",
        shipment.Status.COMPLETED: "Доставка завершена",
        shipment.Status.CANCELED: "Доставка отменена",
    }
    client_body_map = {
        shipment.Status.PENDING: f"Заявка №{shipment.public_code} создана.",
        shipment.Status.ASSIGNED: f"Заказ №{shipment.public_code}: курьер назначен.",
        shipment.Status.IN_TRANSIT: f"Заказ №{shipment.public_code}: курьер в пути.",
        shipment.Status.AWAITING_PAYMENT: f"Заказ №{shipment.public_code} выполнен. Оплатите заказ, чтобы завершить его.",
        shipment.Status.COMPLETED: f"Заказ №{shipment.public_code} успешно доставлен.",
        shipment.Status.CANCELED: f"Заказ №{shipment.public_code} отменён.",
    }
    carrier_body_map = {
        shipment.Status.PENDING: f"Заявка №{shipment.public_code} создана.",
        shipment.Status.ASSIGNED: f"Вы назначены на заказ №{shipment.public_code}.",
        shipment.Status.IN_TRANSIT: f"Заказ №{shipment.public_code}: в пути.",
        shipment.Status.AWAITING_PAYMENT: f"Заказ №{shipment.public_code}: ожидаем оплату клиента.",
        shipment.Status.COMPLETED: f"Заказ №{shipment.public_code} завершён.",
        shipment.Status.CANCELED: f"Заказ №{shipment.public_code} отменён.",
    }

    title = title_map.get(status, "Статус доставки обновлён")

    stops_cnt = shipment.stops.count()
    extra_common = {
        "shipment_id": str(shipment.id),
        "public_code": shipment.public_code,
        "status": shipment.status,
        "stops_count": str(stops_cnt),
        "eta_min": str(shipment.eta_to_next_min) if shipment.eta_to_next_min else "",
        "final_fare": str(shipment.final_fare or shipment.estimated_fare),
    }

    client_data = {
        **_base_data(
            app="client",
            type_="shipment_status",
            title=title,
            body=client_body_map.get(status, ""),
            channel="orders",
            deep_link=f"app://client/shipment/{shipment.id}",
        ),
        **extra_common,
    }
    _send_to_user(
        shipment.client_id,
        client_data,
        ttl="600s",
        collapse_key=f"shipment_{shipment.id}",
    )

    carrier_data = {
        **_base_data(
            app="carrier",
            type_="shipment_status",
            title=title,
            body=carrier_body_map.get(status, ""),
            channel="orders",
            deep_link=f"app://carrier/shipment/{shipment.id}",
        ),
        **extra_common,
    }
    _send_to_user(
        shipment.carrier_id,
        carrier_data,
        ttl="600s",
        collapse_key=f"shipment_{shipment.id}",
    )


def notify_shipment_canceled(shipment, *, reason: str = "") -> None:
    base_extra = {
        "shipment_id": str(shipment.id),
        "public_code": shipment.public_code,
        "reason": reason or "unknown",
    }

    client_data = {
        **_base_data(
            app="client",
            type_="shipment_canceled",
            title="Доставка отменена",
            body=f"Заказ №{shipment.public_code} отменён.",
            channel="orders",
            deep_link="app://client/home",
        ),
        **base_extra,
    }
    _send_to_user(
        shipment.client_id,
        client_data,
        ttl="600s",
        collapse_key=f"shipment_cancel_{shipment.id}",
    )

    carrier_data = {
        **_base_data(
            app="carrier",
            type_="shipment_canceled",
            title="Заказ отменён",
            body=f"Заказ №{shipment.public_code} отменён.",
            channel="orders",
            deep_link="app://carrier/home",
        ),
        **base_extra,
    }
    _send_to_user(
        shipment.carrier_id,
        carrier_data,
        ttl="600s",
        collapse_key=f"shipment_cancel_{shipment.id}",
    )


def broadcast_to_role(
    *,
    role: str,
    app: str,
    title: str,
    body: str,
    channel: str = "system",
    deep_link: str = "",
    type_: str = "manual",
    silent: bool = False,
    ttl: str = "600s",
    collapse_key: str | None = None,
) -> int:
    base = _base_data(
        app=app,
        type_=type_,
        title=title,
        body=body,
        channel=channel,
        deep_link=deep_link,
        silent=silent,
    )

    user_ids = (
        FCMToken.objects.filter(
            user__role=role,
            user__is_active=True,
            is_active=True,
        )
        .values_list("user_id", flat=True)
        .distinct()
    )

    delivered_users = 0
    for user_id in user_ids:
        if _send_to_user(
            user_id,
            dict(base),
            ttl=ttl,
            collapse_key=collapse_key,
        ):
            delivered_users += 1
    return delivered_users
