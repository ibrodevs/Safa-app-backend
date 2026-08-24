import logging

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.payments.finik import (
    FinikVerificationUnavailable,
    find_finik_item_by_request_id,
    finik_item_matches_attempt,
    verify_finik_payment,
)
from apps.payments.models import AmanatPaymentAttempt, CarrierSettlement, PaymentAttempt

from admin_panel.access import staff_required
from .common import panel_render


logger = logging.getLogger("payments.finik")


@staff_required
def finance(request):
    status = request.GET.get("status", "")
    payments = PaymentAttempt.objects.select_related(
        "shipment", "shipment__client"
    ).order_by("-created_at")
    if status in PaymentAttempt.Status.values:
        payments = payments.filter(status=status)
    today = timezone.localdate()
    metrics = {
        "paid_today": PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.SUCCEEDED,
            updated_at__date=today,
        ).aggregate(total=Sum("amount"))["total"]
        or 0,
        "succeeded": PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.SUCCEEDED
        ).count(),
        "pending": PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.PENDING
        ).count(),
        "failed": PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.FAILED
        ).count(),
        "settled": CarrierSettlement.objects.aggregate(total=Sum("net_amount"))[
            "total"
        ]
        or 0,
    }
    page = Paginator(payments, 25).get_page(request.GET.get("page"))
    settlements = CarrierSettlement.objects.select_related(
        "shipment", "carrier"
    )[:10]
    amanat_payments = AmanatPaymentAttempt.objects.select_related(
        "donation", "donation__campaign", "donation__donor"
    ).order_by("-created_at")[:10]
    return panel_render(
        request,
        "admin_panel/finance/index.html",
        {
            "metrics": metrics,
            "page": page,
            "settlements": settlements,
            "amanat_payments": amanat_payments,
            "selected_status": status,
        },
        section="finance",
        title="Финансы",
    )


@staff_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        PaymentAttempt.objects.select_related(
            "shipment", "shipment__client", "shipment__carrier"
        ),
        pk=pk,
    )
    return panel_render(
        request,
        "admin_panel/finance/detail.html",
        {"payment": payment},
        section="finance",
        title="Платёж",
    )


@staff_required
@require_POST
def payment_reconcile(request, pk):
    payment = get_object_or_404(
        PaymentAttempt.objects.select_related("shipment"),
        pk=pk,
    )
    wants_json = "application/json" in request.headers.get("Accept", "")
    logger.info(
        "admin_finik_reconcile_started",
        extra={"attempt_id": str(payment.id), "status": payment.status},
    )

    try:
        if payment.status == PaymentAttempt.Status.SUCCEEDED:
            verified_item = None
        elif payment.status == PaymentAttempt.Status.FAILED:
            verified_item = None
        elif payment.finik_transaction_id:
            verified_item = verify_finik_payment(
                payment.finik_transaction_id,
                payment,
                key_type="TRANSACTION_ID",
            )
        elif payment.finik_item_id:
            verified_item = verify_finik_payment(
                payment.finik_item_id,
                payment,
                key_type="ID",
            )
        else:
            candidate = find_finik_item_by_request_id(payment)
            if candidate:
                payment.finik_item_id = str(candidate.get("id") or "")[:128] or None
                payment.save(update_fields=["finik_item_id", "updated_at"])
            verified_item = (
                candidate
                if candidate and finik_item_matches_attempt(candidate, payment)
                else None
            )
    except FinikVerificationUnavailable as exc:
        error_code = exc.code or "finik_verification_unavailable"
        provider_message = exc.provider_message
        logger.exception(
            "admin_finik_reconcile_unavailable",
            extra={
                "attempt_id": str(payment.id),
                "finik_error_code": error_code,
                "finik_provider_message": provider_message,
            },
        )
        if wants_json:
            return JsonResponse(
                {
                    "paid": False,
                    "detail": error_code,
                    "providerMessage": provider_message,
                },
                status=503,
            )
        messages.error(
            request,
            f"Finik не выполнил проверку ({error_code}). "
            f"{provider_message or 'Повторите позже.'}",
        )
        return redirect("admin_panel:payment_detail", pk=payment.pk)

    if payment.status == PaymentAttempt.Status.SUCCEEDED:
        from apps.payments.views import _finish_verified_shipment_payment

        shipment, _ = _finish_verified_shipment_payment(
            attempt_id=payment.id,
            transaction_id=payment.finik_transaction_id or "",
            item_id=payment.finik_item_id or "",
            raw_payload=payment.raw_callback_payload,
        )
        paid = shipment.is_paid
    elif verified_item:
        from apps.payments.views import _finish_verified_shipment_payment

        shipment, _ = _finish_verified_shipment_payment(
            attempt_id=payment.id,
            transaction_id=str(verified_item.get("transactionId") or ""),
            item_id=str(verified_item.get("id") or ""),
            raw_payload={"source": "admin_reconcile_by_request_id"},
        )
        paid = shipment.is_paid
    else:
        paid = False

    if wants_json:
        logger.info(
            "admin_finik_reconcile_finished",
            extra={"attempt_id": str(payment.id), "paid": paid},
        )
        return JsonResponse(
            {"paid": paid, "detail": "confirmed" if paid else "not_confirmed"},
            status=200 if paid else 202,
        )
    if paid:
        messages.success(request, "Оплата подтверждена в Finik, заказ обновлён.")
    else:
        messages.warning(request, "Finik пока не подтвердил оплату этого платежа.")
    return redirect("admin_panel:payment_detail", pk=payment.pk)
