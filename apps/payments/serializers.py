from rest_framework import serializers

from .models import PaymentAttempt

class CreateFinikPaymentOutSerializer(serializers.Serializer):
    paymentId = serializers.UUIDField()
    finikRequestId = serializers.CharField()
    callbackUrl = serializers.URLField()
    requiredFields = serializers.DictField(child=serializers.CharField())
    amount = serializers.IntegerField()
    currency = serializers.CharField()
    accountId = serializers.CharField()

class FinikCallbackInSerializer(serializers.Serializer):
    """
    Мы делаем tolerant-парсер.
    Required fields are echoed by Finik from the hidden fields configured in
    the mobile SDK. They bind a callback to one server-created attempt.
    """
    status = serializers.ChoiceField(choices=["SUCCEEDED", "FAILED"])
    fields = serializers.DictField(required=False)
    requestId = serializers.CharField(required=False, allow_blank=True)
    transactionId = serializers.CharField()
    item = serializers.DictField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    accountId = serializers.CharField()

    def validate(self, attrs):
        fields = attrs.get("fields") or {}
        required = {
            "paymentId": fields.get("paymentId") or fields.get("payment_id"),
            "finikRequestId": fields.get("finikRequestId")
            or fields.get("finik_request_id"),
            "shipmentId": fields.get("shipmentId") or fields.get("shipment_id"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise serializers.ValidationError(
                {"fields": f"required callback fields missing: {', '.join(missing)}"}
            )
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
