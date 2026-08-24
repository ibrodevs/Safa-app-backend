from django.contrib import messages
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.delivery.models import Bazar, Container, DeliveryDistrict, Passage

from admin_panel.access import staff_required
from admin_panel.forms import (
    BazarPanelForm,
    ContainerPanelForm,
    DistrictPanelForm,
    PassagePanelForm,
)

from .common import panel_render


def _query(request):
    return request.GET.get("q", "").strip()


@staff_required
def bazar_list(request):
    query = _query(request)
    items = Bazar.objects.select_related("district_tariff").order_by("name")
    if query:
        items = items.filter(Q(name__icontains=query) | Q(district__icontains=query))
    return panel_render(
        request,
        "admin_panel/catalog/list.html",
        {"items": items, "query": query, "kind": "bazar"},
        section="bazars",
        title="Базары",
    )


@staff_required
def district_list(request):
    query = _query(request)
    items = DeliveryDistrict.objects.order_by("name")
    if query:
        items = items.filter(name__icontains=query)
    return panel_render(
        request,
        "admin_panel/catalog/list.html",
        {"items": items, "query": query, "kind": "district"},
        section="districts",
        title="Районы",
    )


@staff_required
def passage_list(request):
    query = _query(request)
    items = Passage.objects.select_related("bazar").prefetch_related("containers").order_by(
        "bazar__name", "number"
    )
    if query:
        items = items.filter(Q(number__icontains=query) | Q(bazar__name__icontains=query))
    return panel_render(
        request,
        "admin_panel/catalog/list.html",
        {"items": items, "query": query, "kind": "passage"},
        section="passages",
        title="Проходы",
    )


@staff_required
def container_list(request):
    query = _query(request)
    items = Container.objects.select_related("passage", "passage__bazar").order_by(
        "passage__bazar__name", "passage__number", "number"
    )
    if query:
        items = items.filter(
            Q(number__icontains=query)
            | Q(title__icontains=query)
            | Q(passage__number__icontains=query)
            | Q(passage__bazar__name__icontains=query)
        )
    return panel_render(
        request,
        "admin_panel/catalog/list.html",
        {"items": items, "query": query, "kind": "container"},
        section="containers",
        title="Контейнеры",
    )


def _form_page(request, *, instance, form_class, kind, section, title, success_url):
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"«{saved}» сохранено.")
        return redirect(success_url)
    return panel_render(
        request,
        "admin_panel/catalog/form.html",
        {"form": form, "instance": instance, "kind": kind, "back_url": success_url},
        section=section,
        title=title,
    )


@staff_required
@require_http_methods(["GET", "POST"])
def bazar_form(request, pk=None):
    return _form_page(
        request,
        instance=get_object_or_404(Bazar, pk=pk) if pk else None,
        form_class=BazarPanelForm,
        kind="bazar",
        section="bazars",
        title="Редактировать базар" if pk else "Создать базар",
        success_url="admin_panel:bazars",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def district_form(request, pk=None):
    return _form_page(
        request,
        instance=get_object_or_404(DeliveryDistrict, pk=pk) if pk else None,
        form_class=DistrictPanelForm,
        kind="district",
        section="districts",
        title="Редактировать район" if pk else "Создать район",
        success_url="admin_panel:districts",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def passage_form(request, pk=None):
    return _form_page(
        request,
        instance=get_object_or_404(Passage, pk=pk) if pk else None,
        form_class=PassagePanelForm,
        kind="passage",
        section="passages",
        title="Редактировать проход" if pk else "Создать проход",
        success_url="admin_panel:passages",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def container_form(request, pk=None):
    return _form_page(
        request,
        instance=get_object_or_404(Container, pk=pk) if pk else None,
        form_class=ContainerPanelForm,
        kind="container",
        section="containers",
        title="Редактировать контейнер" if pk else "Создать контейнер",
        success_url="admin_panel:containers",
    )


def _delete(request, *, model, pk, success_url, label):
    instance = get_object_or_404(model, pk=pk)
    name = str(instance)
    try:
        instance.delete()
    except ProtectedError:
        messages.error(
            request,
            f"Нельзя удалить {label} «{name}»: объект уже используется. Сначала перенесите связанные данные или отключите объект.",
        )
    else:
        messages.success(request, f"{label.capitalize()} «{name}» удалён.")
    return redirect(success_url)


@staff_required
@require_POST
def bazar_delete(request, pk):
    return _delete(request, model=Bazar, pk=pk, success_url="admin_panel:bazars", label="базар")


@staff_required
@require_POST
def district_delete(request, pk):
    return _delete(request, model=DeliveryDistrict, pk=pk, success_url="admin_panel:districts", label="район")


@staff_required
@require_POST
def passage_delete(request, pk):
    return _delete(request, model=Passage, pk=pk, success_url="admin_panel:passages", label="проход")


@staff_required
@require_POST
def container_delete(request, pk):
    return _delete(request, model=Container, pk=pk, success_url="admin_panel:containers", label="контейнер")
