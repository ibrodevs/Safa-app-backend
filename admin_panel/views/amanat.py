from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from apps.delivery.models import AmanatCampaign, AmanatCategory, AmanatDonation

from admin_panel.access import staff_required
from admin_panel.forms import AmanatCampaignForm, AmanatCategoryForm
from .common import panel_render


def _campaigns():
    return AmanatCampaign.objects.select_related("category").annotate(
        _paid_donations_amount=Coalesce(
            Sum("donations__amount", filter=Q(donations__status=AmanatDonation.Status.PAID)),
            0,
        ),
        _paid_donations_count=Count(
            "donations", filter=Q(donations__status=AmanatDonation.Status.PAID)
        ),
    ).order_by("sort_order", "-created_at")


@staff_required
def amanat_list(request):
    selected = request.GET.get("status", AmanatCampaign.Status.ACTIVE)
    if selected not in AmanatCampaign.Status.values:
        selected = AmanatCampaign.Status.ACTIVE
    page = Paginator(_campaigns().filter(status=selected), 20).get_page(
        request.GET.get("page")
    )
    return panel_render(
        request,
        "admin_panel/amanat/list.html",
        {
            "page": page,
            "selected_status": selected,
            "categories": AmanatCategory.objects.order_by("sort_order", "name"),
        },
        section="amanat",
        title="Amanat",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def amanat_category_form(request, pk=None):
    category = get_object_or_404(AmanatCategory, pk=pk) if pk else None
    form = AmanatCategoryForm(request.POST or None, instance=category)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Категория Amanat сохранена.")
        return redirect("admin_panel:amanat")
    return panel_render(
        request,
        "admin_panel/amanat/category_form.html",
        {"form": form, "category": category},
        section="amanat",
        title="Категория Amanat",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def amanat_create(request):
    form = AmanatCampaignForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        campaign = form.save()
        messages.success(request, "Сбор создан.")
        return redirect("admin_panel:amanat_detail", pk=campaign.pk)
    return panel_render(
        request,
        "admin_panel/amanat/form.html",
        {"form": form, "campaign": None},
        section="amanat",
        title="Новый сбор",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def amanat_detail(request, pk):
    campaign = get_object_or_404(_campaigns(), pk=pk)
    form = AmanatCampaignForm(
        request.POST or None,
        request.FILES or None,
        instance=campaign,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Изменения сбора сохранены.")
        return redirect("admin_panel:amanat_detail", pk=pk)
    donations = campaign.donations.select_related("donor")[:20]
    return panel_render(
        request,
        "admin_panel/amanat/detail.html",
        {"campaign": campaign, "form": form, "donations": donations},
        section="amanat",
        title=campaign.title,
    )
