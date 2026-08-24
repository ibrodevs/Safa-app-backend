from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.delivery.models import Bazar, DeliveryDistrict, GlobalDeliveryConfig

from admin_panel.access import staff_required
from admin_panel.forms import BazarTariffForm, DistrictTariffForm, GlobalTariffForm
from .common import panel_render


@staff_required
def tariff_list(request):
    config = GlobalDeliveryConfig.get_config()
    districts = DeliveryDistrict.objects.order_by("name")
    bazars = Bazar.objects.select_related("district_tariff").order_by("name")
    return panel_render(
        request,
        "admin_panel/tariffs/index.html",
        {
            "config": config,
            "districts": districts,
            "bazars": bazars,
            "global_form": GlobalTariffForm(instance=config),
            "district_form": DistrictTariffForm(),
        },
        section="tariffs",
        title="Тарифы",
    )


@staff_required
@require_POST
def global_tariff_save(request):
    config = GlobalDeliveryConfig.get_config()
    form = GlobalTariffForm(request.POST, instance=config)
    if form.is_valid():
        form.save()
        messages.success(request, "Глобальный тариф сохранён.")
    else:
        messages.error(request, "Проверьте значения глобального тарифа.")
    return redirect("admin_panel:tariffs")


@staff_required
@require_POST
def district_tariff_save(request, pk=None):
    instance = get_object_or_404(DeliveryDistrict, pk=pk) if pk else None
    form = DistrictTariffForm(request.POST, instance=instance)
    if form.is_valid():
        form.save()
        messages.success(request, "Тариф района сохранён.")
    else:
        messages.error(request, "Не удалось сохранить тариф района.")
    return redirect("admin_panel:tariffs")


@staff_required
@require_POST
def bazar_tariff_save(request, pk):
    bazar = get_object_or_404(Bazar.objects.select_related("district_tariff"), pk=pk)
    form = BazarTariffForm(request.POST, instance=bazar)
    if form.is_valid():
        form.save()
        messages.success(request, f"Тариф базара «{bazar.name}» сохранён.")
    else:
        messages.error(request, "Не удалось сохранить тариф базара.")
    return redirect("admin_panel:tariffs")
