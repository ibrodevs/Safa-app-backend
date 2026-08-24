from django.core.paginator import Paginator
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.payments.models import AmanatPaymentAttempt, CarrierSettlement, PaymentAttempt

from admin_panel.access import staff_required
from .common import panel_render


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
