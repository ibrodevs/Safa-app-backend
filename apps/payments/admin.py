from django.contrib import admin

from .models import AmanatPaymentAttempt, CarrierSettlement, PaymentAttempt


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "shipment", "amount", "currency", "status", "created_at")
    readonly_fields = [field.name for field in PaymentAttempt._meta.fields]


@admin.register(AmanatPaymentAttempt)
class AmanatPaymentAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "donation", "amount", "currency", "status", "created_at")
    readonly_fields = [field.name for field in AmanatPaymentAttempt._meta.fields]


@admin.register(CarrierSettlement)
class CarrierSettlementAdmin(admin.ModelAdmin):
    list_display = (
        "shipment",
        "carrier",
        "gross_amount",
        "commission_amount",
        "net_amount",
        "currency",
        "status",
        "credited_at",
    )
    readonly_fields = [field.name for field in CarrierSettlement._meta.fields]
