from rest_framework import serializers

from .models import CarrierSettlement, PaymentAttempt

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
    status = serializers.CharField()
    fields = serializers.DictField(required=False)
    paymentKind = serializers.CharField(required=False, allow_blank=True)
    requestId = serializers.CharField(required=False, allow_blank=True)
    transactionId = serializers.CharField()
    item = serializers.DictField(required=False)
    data = serializers.DictField(required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    accountId = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        status = str(attrs.get("status") or "").strip().upper()
        if status not in {"SUCCEEDED", "FAILED"}:
            raise serializers.ValidationError({"status": "unsupported status"})
        attrs["status"] = status

        item = attrs.get("item") or {}
        data = attrs.get("data") or {}
        item_account = item.get("account") if isinstance(item, dict) else {}
        account_id = (
            attrs.get("accountId")
            or (data.get("accountId") if isinstance(data, dict) else None)
            or (
                item_account.get("id")
                if isinstance(item_account, dict)
                else None
            )
        )
        if not account_id:
            raise serializers.ValidationError({"accountId": "required"})
        attrs["accountId"] = str(account_id)

        fields = attrs.get("fields") or {}
        payment_kind = str(
            fields.get("paymentKind")
            or fields.get("payment_kind")
            or attrs.get("paymentKind")
            or ("amanat" if fields.get("donationId") else "shipment")
        ).strip().lower()
        if payment_kind not in {"shipment", "amanat"}:
            raise serializers.ValidationError(
                {"fields": "unsupported paymentKind"}
            )
        attrs["paymentKind"] = payment_kind
        required = {
            "paymentId": fields.get("paymentId") or fields.get("payment_id"),
            "finikRequestId": fields.get("finikRequestId")
            or fields.get("finik_request_id"),
        }
        if payment_kind == "amanat":
            required.update(
                {
                    "donationId": fields.get("donationId")
                    or fields.get("donation_id"),
                    "campaignId": fields.get("campaignId")
                    or fields.get("campaign_id"),
                }
            )
        else:
            required["shipmentId"] = fields.get("shipmentId") or fields.get(
                "shipment_id"
            )
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise serializers.ValidationError(
                {"fields": f"required callback fields missing: {', '.join(missing)}"}
            )
        return attrs


class FinikReconcileInSerializer(serializers.Serializer):
    paymentId = serializers.UUIDField()
    itemId = serializers.CharField(required=False, allow_blank=True, max_length=128)
    transactionId = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=128,
    )

    def validate(self, attrs):
        if not attrs.get("itemId") and not attrs.get("transactionId"):
            raise serializers.ValidationError(
                {"detail": "itemId_or_transactionId_required"}
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


class CarrierSettlementSerializer(serializers.ModelSerializer):
    shipment_code = serializers.CharField(
        source="shipment.public_code",
        read_only=True,
    )

    class Meta:
        model = CarrierSettlement
        fields = [
            "id",
            "shipment",
            "shipment_code",
            "gross_amount",
            "commission_amount",
            "net_amount",
            "currency",
            "status",
            "credited_at",
        ]
        read_only_fields = fields
