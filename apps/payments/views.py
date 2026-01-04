from uuid import UUID
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status as drf_status

from apps.payments.models import PaymentAttempt

class FinikCallbackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data
        status_in = payload.get("status")
        fields = payload.get("fields") or {}
        payment_id = fields.get("paymentId")

        if status_in not in ("SUCCEEDED", "FAILED") or not payment_id:
            return Response({"detail": "invalid_payload"}, status=drf_status.HTTP_400_BAD_REQUEST)

        try:
            attempt_id = UUID(str(payment_id))
        except Exception:
            return Response({"detail": "invalid_paymentId"}, status=drf_status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            try:
                attempt = PaymentAttempt.objects.select_for_update().select_related("shipment").get(id=attempt_id)
            except PaymentAttempt.DoesNotExist:
                return Response({"detail": "payment_not_found"}, status=drf_status.HTTP_404_NOT_FOUND)

            attempt.raw_callback_payload = payload

            # идемпотентность
            if attempt.status in (PaymentAttempt.Status.SUCCEEDED, PaymentAttempt.Status.FAILED):
                attempt.save(update_fields=["raw_callback_payload", "updated_at"])
                return Response({"ok": True})

            if status_in == "SUCCEEDED":
                attempt.status = PaymentAttempt.Status.SUCCEEDED
                s = attempt.shipment
                if not s.is_paid:
                    s.is_paid = True
                    s.paid_at = timezone.now()
                    s.save(update_fields=["is_paid", "paid_at"])
            else:
                attempt.status = PaymentAttempt.Status.FAILED

            attempt.save(update_fields=["status", "raw_callback_payload", "updated_at"])

        return Response({"ok": True})
