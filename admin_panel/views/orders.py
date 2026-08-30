from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.delivery.models import Shipment
from apps.delivery.operations import (
    cancel_shipment,
    normalize_shipment_stops,
    reestimate_shipment,
    sync_shipment_admin_state,
)

from admin_panel.access import staff_required
from admin_panel.forms import ShipmentPanelForm, ShipmentStopFormSet
from .common import panel_render


STATUS_LABELS = dict(Shipment.Status.choices)


def _orders_queryset():
    return (
        Shipment.objects.exclude(is_demo=True)
        .select_related("client", "carrier", "review")
        .prefetch_related("stops")
    )


@staff_required
def order_list(request):
    queryset = _orders_queryset()
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    service = request.GET.get("service", "").strip()
    period = request.GET.get("period", "").strip()

    if query:
        search = (
            Q(title__icontains=query)
            | Q(client__first_name__icontains=query)
            | Q(client__phone_number__icontains=query)
            | Q(carrier__first_name__icontains=query)
            | Q(carrier__phone_number__icontains=query)
        )
        if query.lstrip("#").isdigit():
            search |= Q(pk=int(query.lstrip("#")))
        queryset = queryset.filter(search)
    if status in Shipment.Status.values:
        queryset = queryset.filter(status=status)
    if service in Shipment.ServiceType.values:
        queryset = queryset.filter(service_type=service)
    if period in {"today", "7", "30"}:
        from datetime import timedelta
        from django.utils import timezone

        days = 0 if period == "today" else int(period) - 1
        queryset = queryset.filter(
            created_at__date__gte=timezone.localdate() - timedelta(days=days)
        )

    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return panel_render(
        request,
        "admin_panel/orders/list.html",
        {
            "page": page,
            "query": query,
            "selected_status": status,
            "selected_service": service,
            "selected_period": period,
            "statuses": Shipment.Status.choices,
            "services": Shipment.ServiceType.choices,
        },
        section="orders",
        title="Заказы",
    )


def _order(pk):
    return get_object_or_404(
        _orders_queryset().prefetch_related("payment_attempts"),
        pk=pk,
    )


@staff_required
def order_detail(request, pk):
    shipment = _order(pk)
    return panel_render(
        request,
        "admin_panel/orders/detail.html",
        {"shipment": shipment, "status_label": STATUS_LABELS.get(shipment.status)},
        section="orders",
        title=f"Заказ #{shipment.public_code}",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def order_form(request, pk=None):
    shipment = get_object_or_404(Shipment, pk=pk) if pk else Shipment()
    form = ShipmentPanelForm(request.POST or None, instance=shipment)
    formset = ShipmentStopFormSet(
        request.POST or None,
        instance=shipment,
        prefix="stops",
    )
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            shipment = form.save(commit=False)
            sync_shipment_admin_state(shipment)
            shipment.save()
            if shipment.pk:
                shipment.stops.filter(position__isnull=False).update(position=F("position") + 1000)
            formset.save(commit=False)
            for deleted in formset.deleted_objects:
                deleted.delete()
            ordered = [
                stop_form
                for stop_form in formset.ordered_forms
                if stop_form.instance.pk
                or any(
                    stop_form.cleaned_data.get(name) not in (None, "")
                    for name in ("container", "title", "lat", "lon")
                )
            ]
            for position, stop_form in enumerate(ordered):
                stop = stop_form.save(commit=False)
                stop.shipment = shipment
                stop.position = position
                stop.save()
            normalize_shipment_stops(shipment)
        messages.success(
            request,
            f"Заказ #{shipment.public_code} {'обновлён' if pk else 'создан'}.",
        )
        return redirect("admin_panel:order_detail", pk=shipment.pk)
    return panel_render(
        request,
        "admin_panel/orders/form.html",
        {"form": form, "formset": formset, "shipment": shipment if pk else None},
        section="orders",
        title="Редактирование заказа" if pk else "Новый заказ",
    )


@staff_required
def order_quick(request, pk):
    shipment = _order(pk)
    return panel_render(
        request,
        "admin_panel/orders/quick.html",
        {"shipment": shipment, "status_label": STATUS_LABELS.get(shipment.status)},
        section="orders",
        title=f"Заказ #{shipment.public_code}",
    )


@staff_required
@require_POST
def order_cancel(request, pk):
    shipment = _order(pk)
    try:
        cancel_shipment(shipment)
    except ValueError:
        messages.error(request, "Этот заказ уже нельзя отменить.")
    else:
        messages.success(request, f"Заказ #{shipment.public_code} отменён.")
    return redirect("admin_panel:order_detail", pk=pk)


@staff_required
@require_POST
def order_recalculate(request, pk):
    shipment = _order(pk)
    try:
        reestimate_shipment(shipment)
    except ValueError:
        messages.error(request, "Стоимость завершённого заказа нельзя изменить.")
    else:
        messages.success(request, "Стоимость заказа пересчитана.")
    return redirect("admin_panel:order_detail", pk=pk)
