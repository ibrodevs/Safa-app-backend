import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.delivery.models import Shipment


class PaymentAttempt(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        SUCCEEDED = "SUCCEEDED"
        FAILED = "FAILED"

    class Provider(models.TextChoices):
        FINIK = "FINIK"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="payment_attempts",
    )

    provider = models.CharField(
        max_length=16,
        choices=Provider.choices,
        default=Provider.FINIK,
    )

    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=8, default="KGS")

    finik_request_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    finik_transaction_id = models.CharField(max_length=128, null=True, blank=True)
    finik_item_id = models.CharField(max_length=128, null=True, blank=True)
    raw_callback_payload = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class CarrierSettlement(models.Model):
    """Immutable internal credit created once after a verified payment."""

    class Status(models.TextChoices):
        CREDITED = "CREDITED", "Начислено"

    shipment = models.OneToOneField(
        Shipment,
        on_delete=models.PROTECT,
        related_name="carrier_settlement",
    )
    payment_attempt = models.OneToOneField(
        PaymentAttempt,
        on_delete=models.PROTECT,
        related_name="carrier_settlement",
    )
    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="carrier_settlements",
    )
    gross_amount = models.PositiveIntegerField()
    commission_amount = models.PositiveIntegerField()
    net_amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=8, default="KGS")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.CREDITED,
    )
    credited_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-credited_at",)
