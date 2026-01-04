from uuid import UUID
import logging

from rest_framework import serializers, status
from apps.delivery.models import Shipment
from .models import PaymentAttempt, new_finik_request_id

logger = logging.getLogger("payments.finik")

class CreateFinikPaymentOutSerializer(serializers.Serializer):
    paymentId = serializers.UUIDField()
    finikRequestId = serializers.CharField()
    callbackUrl = serializers.URLField()
    requiredFields = serializers.DictField(child=serializers.CharField())
    amount = serializers.IntegerField()
    currency = serializers.CharField()

class FinikCallbackInSerializer(serializers.Serializer):
    """
    Мы делаем tolerant-парсер.
    ОБЯЗАТЕЛЬНО: status и fields.paymentId (мы сами его кладём в requiredFields).
    """
    status = serializers.ChoiceField(choices=["SUCCEEDED", "FAILED"])
    fields = serializers.DictField(required=False)
    requestId = serializers.CharField(required=False, allow_blank=True)
    transactionId = serializers.CharField(required=False, allow_blank=True)
    item = serializers.DictField(required=False)

    def validate(self, attrs):
        fields = attrs.get("fields") or {}
        pid = fields.get("paymentId") or fields.get("payment_id")
        if not pid:
            raise serializers.ValidationError({"fields": "paymentId required in fields"})
        return attrs

class PaymentAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAttempt
        fields = [
            "id", "provider", "shipment",
            "amount", "currency",
            "finik_request_id", "finik_transaction_id", "finik_item_id",
            "status", "created_at", "updated_at",
        ]
        read_only_fields = fields
