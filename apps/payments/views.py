import hashlib
import logging
import secrets
from decimal import Decimal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import CarrierSettlement, PaymentAttempt
from apps.payments.serializers import (
    CarrierSettlementSerializer,
    FinikCallbackInSerializer,
)
from apps.payments.finik import (
    FinikVerificationUnavailable,
    verify_finik_transaction,
)
from apps.payments.settlement import complete_paid_shipment
from apps.delivery.rating import apply_rating_for_completed_shipment
from apps.notification.events import notify_shipment_status


logger = logging.getLogger("payments.finik")


class FinikConfigView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        api_key = str(getattr(settings, "FINIK_API_KEY", "") or "").strip()
        account_id = str(
            getattr(settings, "FINIK_ACCOUNT_ID", "") or ""
        ).strip()
        return Response(
            {
                "paymentFlowVersion": 2,
                "configured": bool(api_key and account_id),
                "keyFingerprint": (
                    hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
                    if api_key
                    else ""
                ),
                "beta": bool(getattr(settings, "FINIK_BETA", False)),
                "testAmount": getattr(settings, "FINIK_TEST_AMOUNT", None),
                "callbackUrl": str(
                    getattr(settings, "FINIK_CALLBACK_URL", "") or ""
                ).strip(),
            }
        )


def _same(left: object, right: object) -> bool:
    return secrets.compare_digest(str(left), str(right))


class CarrierWalletView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if getattr(request.user, "role", None) != "carrier":
            return Response(
                {"detail": "only_for_carrier"},
                status=drf_status.HTTP_403_FORBIDDEN,
            )

        settlements = CarrierSettlement.objects.filter(carrier=request.user)
        balance = settlements.aggregate(total=Sum("net_amount"))["total"] or 0
        recent = settlements.select_related("shipment")[:50]
        return Response(
            {
                "balance": int(balance),
                "currency": "KGS",
                "settlements": CarrierSettlementSerializer(
                    recent,
                    many=True,
                ).data,
            }
        )


class FinikCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = FinikCallbackInSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("finik_callback_invalid_payload")
            return Response(
                {"detail": "invalid_payload"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        payload = serializer.validated_data
        fields = payload["fields"]
        payment_id = fields.get("paymentId") or fields.get("payment_id")

        try:
            attempt_id = UUID(str(payment_id))
        except (TypeError, ValueError, AttributeError):
            return Response(
                {"detail": "invalid_paymentId"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            attempt = PaymentAttempt.objects.select_related("shipment").get(
                id=attempt_id
            )
        except PaymentAttempt.DoesNotExist:
            return Response(
                {"detail": "payment_not_found"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        finik_request_id = fields.get("finikRequestId") or fields.get(
            "finik_request_id"
        )
        shipment_id = fields.get("shipmentId") or fields.get("shipment_id")
        configured_account_id = str(
            getattr(settings, "FINIK_ACCOUNT_ID", "") or ""
        ).strip()

        callback_matches = (
            _same(finik_request_id, attempt.finik_request_id)
            and _same(shipment_id, attempt.shipment_id)
            and Decimal(payload["amount"]) == Decimal(attempt.amount)
            and bool(configured_account_id)
            and _same(payload["accountId"], configured_account_id)
        )
        if not callback_matches:
            logger.warning(
                "finik_callback_verification_failed",
                extra={"attempt_id": str(attempt.id)},
            )
            return Response(
                {"detail": "callback_verification_failed"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        try:
            transaction_verified = verify_finik_transaction(
                payload["transactionId"], attempt
            )
        except FinikVerificationUnavailable:
            logger.exception(
                "finik_transaction_verification_unavailable",
                extra={"attempt_id": str(attempt.id)},
            )
            return Response(
                {"detail": "finik_verification_unavailable"},
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not transaction_verified:
            logger.warning(
                "finik_transaction_verification_failed",
                extra={"attempt_id": str(attempt.id)},
            )
            return Response(
                {"detail": "transaction_not_verified"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        completed_shipment = None
        with transaction.atomic():
            attempt = (
                PaymentAttempt.objects.select_for_update()
                .select_related("shipment")
                .get(id=attempt_id)
            )
            raw_payload = request.data
            if attempt.status in (
                PaymentAttempt.Status.SUCCEEDED,
                PaymentAttempt.Status.FAILED,
            ):
                attempt.raw_callback_payload = raw_payload
                attempt.save(update_fields=["raw_callback_payload", "updated_at"])
                return Response({"ok": True})

            transaction_id = payload["transactionId"]
            item = payload.get("item") or {}
            item_id = item.get("id") if isinstance(item, dict) else ""

            attempt.raw_callback_payload = raw_payload
            attempt.finik_transaction_id = str(transaction_id)[:128] or None
            attempt.finik_item_id = str(item_id)[:128] or None

            if payload["status"] == PaymentAttempt.Status.SUCCEEDED:
                attempt.status = PaymentAttempt.Status.SUCCEEDED
                shipment = attempt.shipment
                if shipment.status not in (
                    shipment.Status.AWAITING_PAYMENT,
                    shipment.Status.COMPLETED,
                ):
                    return Response(
                        {"detail": "payment_not_due"},
                        status=drf_status.HTTP_409_CONFLICT,
                    )
                if not shipment.is_paid:
                    shipment.is_paid = True
                    shipment.paid_at = timezone.now()
                    shipment.save(update_fields=["is_paid", "paid_at"])
            else:
                attempt.status = PaymentAttempt.Status.FAILED

            attempt.save(
                update_fields=[
                    "status",
                    "finik_transaction_id",
                    "finik_item_id",
                    "raw_callback_payload",
                    "updated_at",
                ]
            )

            if attempt.status == PaymentAttempt.Status.SUCCEEDED:
                complete_paid_shipment(
                    shipment=shipment,
                    payment_attempt=attempt,
                )
                completed_shipment = shipment

        if completed_shipment is not None:
            apply_rating_for_completed_shipment(completed_shipment)
            notify_shipment_status(completed_shipment)

        return Response({"ok": True})
