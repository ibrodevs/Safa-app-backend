import json
import os

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.delivery.map_admin import other_bazar_boundaries
from apps.delivery.map_cleanup import (
    delete_bazar_with_map,
    describe_map_purge,
    purge_bazar_map,
)
from apps.delivery.map_models import MarketMapRevision
from apps.delivery.map_tariff_sync import attach_district_tariff_ids
from apps.delivery.map_validation import validate_feature_collection
from apps.delivery.models import Bazar, Container, DeliveryDistrict, Passage

from admin_panel.access import staff_required
from admin_panel.forms import BazarPanelForm
from .common import panel_render


def _revision_summary(bazar):
    revisions = list(bazar.map_revisions.all())
    draft = next((item for item in revisions if item.status == MarketMapRevision.Status.DRAFT), None)
    published = next(
        (item for item in revisions if item.status == MarketMapRevision.Status.PUBLISHED),
        None,
    )
    return {"bazar": bazar, "draft": draft, "published": published}


@staff_required
def map_list(request):
    bazars = Bazar.objects.prefetch_related("map_revisions").order_by("name")
    items = [_revision_summary(bazar) for bazar in bazars]
    return panel_render(
        request,
        "admin_panel/map/list.html",
        {"items": items},
        section="map",
        title="Карта",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def bazar_form(request, pk=None):
    bazar = get_object_or_404(Bazar, pk=pk) if pk else None
    form = BazarPanelForm(request.POST or None, instance=bazar)
    if request.method == "POST" and form.is_valid():
        bazar = form.save()
        messages.success(request, f"Базар «{bazar.name}» сохранён.")
        return redirect("admin_panel:map_editor", pk=bazar.pk)
    return panel_render(
        request,
        "admin_panel/map/bazar_form.html",
        {"form": form, "bazar": bazar},
        section="map",
        title="Настройки базара" if bazar else "Новый базар",
    )


def _editor_context(request, bazar):
    revision, _ = MarketMapRevision.get_or_create_draft(
        bazar=bazar,
        user=request.user,
    )
    passages = list(
        Passage.objects.filter(bazar=bazar)
        .order_by("district", "number")
        .values("id", "number", "district")
    )
    containers = list(
        Container.objects.filter(passage__bazar=bazar)
        .select_related("passage")
        .order_by("passage__district", "passage__number", "number")
        .values("id", "number", "title", "passage_id", "passage__number", "passage__district", "lat", "lon")
    )
    for item in containers:
        item["lat"] = float(item["lat"])
        item["lon"] = float(item["lon"])
    return {
        "bazar": bazar,
        "all_bazars": Bazar.objects.order_by("name"),
        "revision": revision,
        "initial_geojson": revision.geojson,
        "context_geojson": other_bazar_boundaries(bazar),
        "passages": passages,
        "containers": containers,
        "district_tariffs": list(
            DeliveryDistrict.objects.filter(is_active=True).values("id", "name")
        ),
        "google_maps_api_key": os.getenv("GOOGLE_MAPS_BROWSER_API_KEY", "")
        or os.getenv("GOOGLE_MAPS_API_KEY", ""),
        "save_url": f"/panel/map/{bazar.pk}/save/",
        "publish_url": f"/panel/map/{bazar.pk}/publish/",
    }


@staff_required
def map_editor(request, pk):
    bazar = get_object_or_404(Bazar, pk=pk)
    return panel_render(
        request,
        "admin_panel/map/editor.html",
        _editor_context(request, bazar),
        section="map",
        title=f"Карта · {bazar.name}",
    )


def _read_geojson(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Не удалось прочитать данные карты") from exc
    return attach_district_tariff_ids(validate_feature_collection(payload.get("geojson")))


@staff_required
@require_POST
def map_save(request, pk):
    bazar = get_object_or_404(Bazar, pk=pk)
    revision, _ = MarketMapRevision.get_or_create_draft(bazar=bazar, user=request.user)
    try:
        revision.geojson = _read_geojson(request)
        revision.full_clean()
        revision.save(update_fields=("geojson", "updated_at"))
    except ValidationError as exc:
        return JsonResponse({"ok": False, "errors": exc.messages}, status=400)
    return JsonResponse(
        {
            "ok": True,
            "version": revision.version,
            "status": revision.status,
            "updated_at": revision.updated_at.isoformat(),
        }
    )


@staff_required
@require_POST
def map_publish(request, pk):
    bazar = get_object_or_404(Bazar, pk=pk)
    revision, _ = MarketMapRevision.get_or_create_draft(bazar=bazar, user=request.user)
    try:
        revision.geojson = _read_geojson(request)
        revision.full_clean()
        revision.save(update_fields=("geojson", "updated_at"))
        published = revision.publish(user=request.user)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "errors": exc.messages}, status=400)
    messages.success(request, f"Карта «{bazar.name}», версия {published.version}, опубликована.")
    return JsonResponse(
        {
            "ok": True,
            "version": published.version,
            "status": published.status,
            "published_at": published.published_at.isoformat(),
        }
    )


@staff_required
@require_POST
def map_delete(request, pk):
    """Удаляет карту базара вместе с районами, проходами и контейнерами."""
    bazar = get_object_or_404(Bazar, pk=pk)
    stats = purge_bazar_map(bazar)
    messages.success(
        request,
        f"Карта базара «{bazar.name}» удалена: {describe_map_purge(stats)}.",
    )
    return redirect("admin_panel:map_list")


@staff_required
@require_POST
def bazar_delete(request, pk):
    """Удаляет базар целиком — вместе с картой и всеми её объектами."""
    bazar = get_object_or_404(Bazar, pk=pk)
    name = bazar.name
    stats = delete_bazar_with_map(bazar)
    messages.success(
        request,
        f"Базар «{name}» удалён вместе с картой: {describe_map_purge(stats)}.",
    )
    return redirect("admin_panel:map_list")
