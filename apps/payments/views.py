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

from apps.delivery.models import AmanatDonation
from apps.payments.models import (
    AmanatPaymentAttempt,
    CarrierSettlement,
    PaymentAttempt,
)
from apps.payments.serializers import (
    CarrierSettlementSerializer,
    FinikCallbackInSerializer,
    FinikReconcileInSerializer,
)
from apps.payments.finik import (
    FinikVerificationUnavailable,
    find_finik_item_by_request_id,
    finik_item_matches_attempt,
    verify_finik_payment,
    verify_finik_transaction,
)
from apps.payments.settlement import complete_paid_shipment
from apps.payments.amounts import effective_finik_test_amount
from apps.delivery.rating import apply_rating_for_completed_shipment
from apps.delivery.realtime import broadcast_shipment
from apps.notification.events import notify_shipment_status


logger = logging.getLogger("payments.finik")


def _finish_verified_shipment_payment(
    *,
    attempt_id: UUID,
    transaction_id: str = "",
    item_id: str = "",
    raw_payload=None,
):
    """Idempotently complete a verified shipment payment."""

    completed_shipment = None
    with transaction.atomic():
        attempt = (
            PaymentAttempt.objects.select_for_update()
            .select_related("shipment")
            .get(id=attempt_id)
        )
        shipment = attempt.shipment
        if attempt.status == PaymentAttempt.Status.FAILED:
            return shipment, False

        changed = False
        if attempt.status != PaymentAttempt.Status.SUCCEEDED:
            if shipment.status not in (
                shipment.Status.AWAITING_PAYMENT,
                shipment.Status.COMPLETED,
            ):
                raise ValueError("payment_not_due")

            attempt.status = PaymentAttempt.Status.SUCCEEDED
            attempt.finik_transaction_id = str(transaction_id)[:128] or None
            attempt.finik_item_id = str(item_id)[:128] or None
            if raw_payload is not None:
                attempt.raw_callback_payload = raw_payload
            attempt.save(
                update_fields=[
                    "status",
                    "finik_transaction_id",
                    "finik_item_id",
                    "raw_callback_payload",
                    "updated_at",
                ]
            )
            changed = True

        shipment_update_fields = []
        if not shipment.is_paid:
            shipment.is_paid = True
            shipment_update_fields.append("is_paid")
        if shipment.paid_at is None:
            shipment.paid_at = attempt.updated_at or timezone.now()
            shipment_update_fields.append("paid_at")
        if shipment_update_fields:
            shipment.save(update_fields=shipment_update_fields)
            changed = True

        needs_completion = (
            shipment.status != shipment.Status.COMPLETED
            or not CarrierSettlement.objects.filter(shipment=shipment).exists()
        )
        complete_paid_shipment(shipment=shipment, payment_attempt=attempt)
        changed = changed or needs_completion
        completed_shipment = shipment

    if changed:
        apply_rating_for_completed_shipment(completed_shipment)
        notify_shipment_status(completed_shipment)
        broadcast_shipment(completed_shipment)
    return completed_shipment, changed


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
                "paymentFlowVersion": 3,
                "paymentPurposes": ["shipment", "amanat"],
                "configured": bool(api_key and account_id),
                "keyFingerprint": (
                    hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
                    if api_key
                    else ""
                ),
                "beta": bool(getattr(settings, "FINIK_BETA", False)),
                "testAmount": effective_finik_test_amount(),
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


class FinikReconcileView(APIView):
    """Recover a successful mobile payment when the callback is delayed/lost."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FinikReconcileInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            attempt = PaymentAttempt.objects.select_related("shipment").get(
                id=payload["paymentId"]
            )
        except PaymentAttempt.DoesNotExist:
            return Response(
                {"detail": "payment_not_found"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        if attempt.shipment.client_id != request.user.id:
            return Response(
                {"detail": "payment_not_found"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )
        if attempt.status == PaymentAttempt.Status.SUCCEEDED:
            try:
                shipment, _ = _finish_verified_shipment_payment(
                    attempt_id=attempt.id,
                    transaction_id=attempt.finik_transaction_id or "",
                    item_id=attempt.finik_item_id or "",
                    raw_payload=attempt.raw_callback_payload,
                )
            except ValueError:
                return Response(
                    {"detail": "payment_not_due"},
                    status=drf_status.HTTP_409_CONFLICT,
                )
            return Response(
                {
                    "paid": True,
                    "status": shipment.status,
                }
            )
        if attempt.status == PaymentAttempt.Status.FAILED:
            return Response(
                {"paid": False, "status": attempt.shipment.status},
                status=drf_status.HTTP_409_CONFLICT,
            )

        transaction_id = str(payload.get("transactionId") or "").strip()
        item_id = str(payload.get("itemId") or attempt.finik_item_id or "").strip()
        if item_id and not attempt.finik_item_id:
            # The authenticated client receives this ID as soon as Finik creates
            # the item. Saving it now lets the server recover if the callback is
            # delayed and the payment screen is closed.
            attempt.finik_item_id = item_id[:128]
            attempt.save(update_fields=["finik_item_id", "updated_at"])
        identifier = transaction_id or item_id
        key_type = "TRANSACTION_ID" if transaction_id else "ID"
        try:
            if identifier:
                verified_item = verify_finik_payment(
                    identifier,
                    attempt,
                    key_type=key_type,
                )
            else:
                candidate = find_finik_item_by_request_id(attempt)
                if candidate and not attempt.finik_item_id:
                    attempt.finik_item_id = str(candidate.get("id") or "")[:128] or None
                    attempt.save(update_fields=["finik_item_id", "updated_at"])
                verified_item = (
                    candidate
                    if candidate and finik_item_matches_attempt(candidate, attempt)
                    else None
                )
        except FinikVerificationUnavailable:
            logger.exception(
                "finik_reconcile_unavailable",
                extra={"attempt_id": str(attempt.id)},
            )
            return Response(
                {"detail": "finik_verification_unavailable"},
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if verified_item is None:
            # A newly created item legitimately has paymentCount=0 until Finik
            # finishes processing. The app retries this response briefly.
            return Response(
                {"paid": False, "status": attempt.shipment.status},
                status=drf_status.HTTP_202_ACCEPTED,
            )

        verified_transaction_id = transaction_id or str(
            verified_item.get("transactionId") or ""
        )
        verified_item_id = item_id or str(verified_item.get("id") or "")
        try:
            shipment, _ = _finish_verified_shipment_payment(
                attempt_id=attempt.id,
                transaction_id=verified_transaction_id,
                item_id=verified_item_id,
                raw_payload={"source": "mobile_reconcile"},
            )
        except ValueError:
            return Response(
                {"detail": "payment_not_due"},
                status=drf_status.HTTP_409_CONFLICT,
            )
        return Response({"paid": shipment.is_paid, "status": shipment.status})


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

        payment_kind = payload["paymentKind"]
        attempt_model = (
            AmanatPaymentAttempt if payment_kind == "amanat" else PaymentAttempt
        )
        attempt_qs = attempt_model.objects
        if payment_kind == "amanat":
            attempt_qs = attempt_qs.select_related("donation__campaign")
        else:
            attempt_qs = attempt_qs.select_related("shipment")
        try:
            attempt = attempt_qs.get(id=attempt_id)
        except attempt_model.DoesNotExist:
            return Response(
                {"detail": "payment_not_found"},
                status=drf_status.HTTP_404_NOT_FOUND,
            )

        finik_request_id = fields.get("finikRequestId") or fields.get(
            "finik_request_id"
        )
        if payment_kind == "amanat":
            target_matches = (
                _same(
                    fields.get("donationId") or fields.get("donation_id"),
                    attempt.donation_id,
                )
                and _same(
                    fields.get("campaignId") or fields.get("campaign_id"),
                    attempt.donation.campaign_id,
                )
            )
        else:
            target_matches = _same(
                fields.get("shipmentId") or fields.get("shipment_id"),
                attempt.shipment_id,
            )
        configured_account_id = str(
            getattr(settings, "FINIK_ACCOUNT_ID", "") or ""
        ).strip()

        callback_matches = (
            _same(finik_request_id, attempt.finik_request_id)
            and target_matches
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

        if payment_kind == "amanat":
            return self._process_amanat_callback(
                request=request,
                payload=payload,
                attempt_id=attempt_id,
            )

        if attempt.status == PaymentAttempt.Status.SUCCEEDED:
            try:
                _finish_verified_shipment_payment(
                    attempt_id=attempt.id,
                    transaction_id=attempt.finik_transaction_id or "",
                    item_id=attempt.finik_item_id or "",
                    raw_payload=request.data,
                )
            except ValueError:
                return Response(
                    {"detail": "payment_not_due"},
                    status=drf_status.HTTP_409_CONFLICT,
                )
            return Response({"ok": True})

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
            broadcast_shipment(completed_shipment)

        return Response({"ok": True})

    def _process_amanat_callback(self, *, request, payload, attempt_id):
        with transaction.atomic():
            attempt = (
                AmanatPaymentAttempt.objects.select_for_update()
                .select_related("donation")
                .get(id=attempt_id)
            )
            donation = attempt.donation
            attempt.raw_callback_payload = request.data

            if attempt.status in (
                PaymentAttempt.Status.SUCCEEDED,
                PaymentAttempt.Status.FAILED,
            ):
                attempt.save(
                    update_fields=["raw_callback_payload", "updated_at"]
                )
                return Response({"ok": True})

            transaction_id = payload["transactionId"]
            item = payload.get("item") or {}
            item_id = item.get("id") if isinstance(item, dict) else ""
            attempt.finik_transaction_id = str(transaction_id)[:128] or None
            attempt.finik_item_id = str(item_id)[:128] or None

            if payload["status"] == PaymentAttempt.Status.SUCCEEDED:
                attempt.status = PaymentAttempt.Status.SUCCEEDED
                donation.status = AmanatDonation.Status.PAID
                donation.paid_at = donation.paid_at or timezone.now()
                donation.save(update_fields=["status", "paid_at"])
            else:
                attempt.status = PaymentAttempt.Status.FAILED
                donation.status = AmanatDonation.Status.FAILED
                donation.save(update_fields=["status"])

            attempt.save(
                update_fields=[
                    "status",
                    "finik_transaction_id",
                    "finik_item_id",
                    "raw_callback_payload",
                    "updated_at",
                ]
            )
        return Response({"ok": True})
