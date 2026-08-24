from django.db.models import Sum
from django.utils import timezone

from apps.delivery.models import Shipment
from apps.payments.models import PaymentAttempt
from apps.users.models import CourierKYC

from admin_panel.access import staff_required
from .common import panel_render


@staff_required
def dashboard(request):
    today = timezone.localdate()
    orders = Shipment.objects.exclude(is_demo=True)
    active_statuses = (
        Shipment.Status.PENDING,
        Shipment.Status.ASSIGNED,
        Shipment.Status.IN_TRANSIT,
        Shipment.Status.AWAITING_PAYMENT,
    )
    succeeded_today = PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.SUCCEEDED,
        updated_at__date=today,
    )
    metrics = {
        "today": orders.filter(created_at__date=today).count(),
        "active": orders.filter(status__in=active_statuses).count(),
        "completed": orders.filter(
            status=Shipment.Status.COMPLETED,
            finished_at__date=today,
        ).count(),
        "revenue": succeeded_today.aggregate(total=Sum("amount"))["total"] or 0,
    }
    attention = {
        "kyc": CourierKYC.objects.filter(status=CourierKYC.Status.PENDING).count(),
        "failed_payments": PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.FAILED
        ).count(),
        "awaiting_payment": orders.filter(
            status=Shipment.Status.AWAITING_PAYMENT
        ).count(),
    }
    recent_orders = orders.select_related("client", "carrier")[:8]
    return panel_render(
        request,
        "admin_panel/dashboard/index.html",
        {"metrics": metrics, "attention": attention, "recent_orders": recent_orders},
        section="dashboard",
        title="Обзор",
    )
