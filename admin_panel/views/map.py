import json
import os

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods, require_POST

from apps.delivery.map_cleanup import (
    delete_bazar_with_map,
    describe_map_purge,
    purge_bazar_map,
)
from apps.delivery.map_collaboration import (
    MapEditConflict,
    publish_collaborative_map,
    save_collaborative_map,
)
from apps.delivery.map_models import MarketMapRevision
from apps.delivery.models import Bazar, DeliveryDistrict

from admin_panel.access import staff_required
from admin_panel.forms import BazarPanelForm
from .common import panel_render

@staff_required
def map_list(request):
    bazar = None
    for revision in MarketMapRevision.objects.select_related("bazar").order_by("-updated_at"):
        if any(
            (feature.get("properties") or {}).get("kind") == "district"
            for feature in (revision.geojson or {}).get("features", [])
        ):
            bazar = revision.bazar
            break
    bazar = bazar or Bazar.objects.order_by("id").first()
    if bazar is None:
        bazar = Bazar.objects.create(name="Карта районов")
    return panel_render(
        request,
        "admin_panel/map/editor.html",
        _editor_context(request, bazar),
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
    district_geojson = {
        "type": "FeatureCollection",
        "features": [
            feature
            for feature in (revision.geojson or {}).get("features", [])
            if (feature.get("properties") or {}).get("kind") == "district"
        ],
    }
    return {
        "bazar": bazar,
        "revision": revision,
        "initial_geojson": district_geojson,
        "districts": list(
            DeliveryDistrict.objects.order_by("name").values(
                "id", "name", "is_active", "per_km_price", "min_fare"
            )
        ),
        "yandex_maps_api_key": os.getenv("YANDEX_MAPS_BROWSER_API_KEY", "")
        or os.getenv("YANDEX_API_KEY", ""),
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
    return payload.get("geojson"), payload.get("base_geojson")


@staff_required
@require_POST
def map_save(request, pk):
    bazar = get_object_or_404(Bazar, pk=pk)
    try:
        submitted, base = _read_geojson(request)
        result = save_collaborative_map(
            bazar=bazar,
            submitted_geojson=submitted,
            base_geojson=base,
            user=request.user,
        )
        revision = result.revision
    except MapEditConflict as exc:
        return JsonResponse({"ok": False, "errors": exc.messages}, status=409)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "errors": exc.messages}, status=400)
    return JsonResponse(
        {
            "ok": True,
            "version": revision.version,
            "status": revision.status,
            "updated_at": revision.updated_at.isoformat(),
            "merged": result.merged,
            # Синхронизация проставила фигурам passage_id/container_id. Без этого
            # ответа редактор не знает о созданных записях, и следующее
            # переименование прохода завело бы новый проход вместо переименования.
            "geojson": revision.geojson,
        }
    )


@staff_required
@require_POST
def map_publish(request, pk):
    bazar = get_object_or_404(Bazar, pk=pk)
    try:
        submitted, base = _read_geojson(request)
        result = publish_collaborative_map(
            bazar=bazar,
            submitted_geojson=submitted,
            base_geojson=base,
            user=request.user,
        )
        published = result.revision
    except MapEditConflict as exc:
        return JsonResponse({"ok": False, "errors": exc.messages}, status=409)
    except ValidationError as exc:
        return JsonResponse({"ok": False, "errors": exc.messages}, status=400)
    messages.success(request, f"Карта «{bazar.name}», версия {published.version}, опубликована.")
    return JsonResponse(
        {
            "ok": True,
            "version": published.version,
            "status": published.status,
            "merged": result.merged,
            "published_at": published.published_at.isoformat(),
            "geojson": published.geojson,
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
    return redirect("admin_panel:districts")


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
