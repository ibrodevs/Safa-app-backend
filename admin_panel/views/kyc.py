from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.users.models import CourierKYC
from apps.users.services.kyc import set_kyc_status

from admin_panel.access import staff_required
from admin_panel.forms import KYCDecisionForm
from .common import panel_render


def _kyc_queryset():
    return CourierKYC.objects.select_related("user").order_by("-created_at")


@staff_required
def kyc_list(request):
    selected = request.GET.get("status", CourierKYC.Status.PENDING)
    if selected not in CourierKYC.Status.values:
        selected = CourierKYC.Status.PENDING
    page = Paginator(_kyc_queryset().filter(status=selected), 24).get_page(
        request.GET.get("page")
    )
    counts = {
        code: _kyc_queryset().filter(status=code).count()
        for code in CourierKYC.Status.values
    }
    return panel_render(
        request,
        "admin_panel/kyc/list.html",
        {"page": page, "selected_status": selected, "counts": counts},
        section="kyc",
        title="Заявки специалистов",
    )


@staff_required
def kyc_detail(request, pk):
    kyc = get_object_or_404(_kyc_queryset(), pk=pk)
    return panel_render(
        request,
        "admin_panel/kyc/detail.html",
        {"kyc": kyc, "form": KYCDecisionForm(initial={"comment": kyc.comment})},
        section="kyc",
        title=f"Проверка {kyc.user.first_name or kyc.user.phone_number}",
    )


def _next_pending(exclude_pk):
    return (
        CourierKYC.objects.filter(status=CourierKYC.Status.PENDING)
        .exclude(pk=exclude_pk)
        .order_by("created_at")
        .values_list("pk", flat=True)
        .first()
    )


@staff_required
@require_POST
def kyc_approve(request, pk):
    kyc = get_object_or_404(_kyc_queryset(), pk=pk)
    form = KYCDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Проверьте комментарий.")
        return redirect("admin_panel:kyc_detail", pk=pk)
    set_kyc_status(
        kyc,
        CourierKYC.Status.APPROVED,
        comment=form.cleaned_data["comment"],
    )
    messages.success(request, "Специалист одобрен и получил доступ к приложению.")
    next_pk = _next_pending(pk)
    return redirect(
        "admin_panel:kyc_detail" if next_pk else "admin_panel:kyc_list",
        **({"pk": next_pk} if next_pk else {}),
    )


@staff_required
@require_POST
def kyc_reject(request, pk):
    kyc = get_object_or_404(_kyc_queryset(), pk=pk)
    form = KYCDecisionForm(request.POST)
    if not form.is_valid() or not form.cleaned_data.get("comment", "").strip():
        messages.error(request, "Укажите причину отклонения.")
        return redirect("admin_panel:kyc_detail", pk=pk)
    set_kyc_status(
        kyc,
        CourierKYC.Status.REJECTED,
        comment=form.cleaned_data["comment"],
    )
    messages.success(request, "Заявка отклонена. Доступ специалиста закрыт.")
    next_pk = _next_pending(pk)
    return redirect(
        "admin_panel:kyc_detail" if next_pk else "admin_panel:kyc_list",
        **({"pk": next_pk} if next_pk else {}),
    )
