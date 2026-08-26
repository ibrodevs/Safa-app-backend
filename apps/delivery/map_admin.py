from __future__ import annotations

import json
import os

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from .map_cleanup import describe_map_purge, purge_bazar_map
from .map_collaboration import (
    MapEditConflict,
    publish_collaborative_map,
    save_collaborative_map,
)
from .map_models import (
    MarketBoundaryMapSection,
    MarketContainerMapSection,
    MarketDistrictMapSection,
    MarketMapRevision,
    MarketPassageMapSection,
)
from .models import Bazar, Container, DeliveryDistrict, Passage


MAP_SECTION_LABELS = {
    "bazar": "границу базара",
    "district": "границу района",
    "passage": "проход",
    "container": "контейнер",
}


def other_bazar_boundaries(current_bazar: Bazar) -> dict:
    features = []
    revisions = (
        MarketMapRevision.objects.filter(status=MarketMapRevision.Status.PUBLISHED)
        .exclude(bazar=current_bazar)
        .select_related("bazar")
    )
    for revision in revisions:
        for feature in revision.geojson.get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "bazar":
                continue
            copy = json.loads(json.dumps(feature))
            copy["id"] = f"readonly-{revision.bazar_id}-{copy.get('id')}"
            copy["properties"] = {
                **copy.get("properties", {}),
                "name": revision.bazar.name,
                "readonly": True,
                "stroke_color": "#475467",
                "fill_color": "#98A2B3",
                "fill_opacity": 0.08,
                "z_index": 1,
            }
            features.append(copy)
    return {"type": "FeatureCollection", "features": features}


@admin.register(MarketMapRevision)
class MarketMapRevisionAdmin(admin.ModelAdmin):
    change_list_template = "admin/delivery/marketmaprevision/change_list.html"
    list_display = (
        "bazar",
        "version",
        "status",
        "updated_at",
        "published_at",
        "created_by",
        "open_editor",
    )
    list_filter = ("status", "bazar")
    search_fields = ("bazar__name",)
    readonly_fields = (
        "bazar",
        "version",
        "status",
        "geojson",
        "created_by",
        "created_at",
        "updated_at",
        "published_at",
    )
    ordering = ("bazar__name", "-version")

    actions = ("delete_bazar_map",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return bool(obj and obj.status == MarketMapRevision.Status.DRAFT and super().has_delete_permission(request, obj))

    @admin.action(description="Удалить карту базара вместе с районами, проходами и контейнерами")
    def delete_bazar_map(self, request, queryset):
        bazars = list(Bazar.objects.filter(pk__in=list(queryset.values_list("bazar_id", flat=True))))
        for bazar in bazars:
            stats = purge_bazar_map(bazar)
            self.message_user(
                request,
                f"Карта базара «{bazar.name}» удалена: {describe_map_purge(stats)}.",
                messages.SUCCESS,
            )

    @admin.display(description="Редактор")
    def open_editor(self, obj: MarketMapRevision):
        url = reverse("admin:delivery_market_map_editor", args=(obj.bazar_id,))
        return format_html('<a class="button" href="{}">Открыть карту</a>', url)

    def get_urls(self):
        custom = [
            path(
                "editor/<int:bazar_id>/",
                self.admin_site.admin_view(self.editor_view),
                name="delivery_market_map_editor",
            ),
            path(
                "editor/<int:bazar_id>/save/",
                self.admin_site.admin_view(require_POST(self.save_view)),
                name="delivery_market_map_save",
            ),
            path(
                "editor/<int:bazar_id>/publish/",
                self.admin_site.admin_view(require_POST(self.publish_view)),
                name="delivery_market_map_publish",
            ),
        ]
        return custom + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context["market_map_bazars"] = Bazar.objects.order_by("name")
        return super().changelist_view(request, extra_context=extra_context)

    def _bazar(self, request, bazar_id: int) -> Bazar:
        if not self.has_change_permission(request):
            raise Http404
        return get_object_or_404(Bazar, pk=bazar_id)

    def editor_view(self, request, bazar_id: int):
        bazar = self._bazar(request, bazar_id)
        focus_kind = request.GET.get("kind", "")
        if focus_kind not in MAP_SECTION_LABELS:
            focus_kind = ""
        revision, _ = MarketMapRevision.get_or_create_draft(bazar=bazar, user=request.user)
        passages = list(
            Passage.objects.filter(bazar=bazar)
            .order_by("district", "number")
            .values("id", "number", "district", "angle")
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

        district_tariffs = list(
            DeliveryDistrict.objects.filter(is_active=True)
            .order_by("name")
            .values(
                "id",
                "name",
                "fixed_price",
                "base_price",
                "per_km_price",
                "min_fare",
            )
        )
        for tariff in district_tariffs:
            for key in ("base_price", "per_km_price", "min_fare"):
                value = tariff[key]
                tariff[key] = str(value) if value is not None else None

        context = {
            **self.admin_site.each_context(request),
            "title": f"Карта базара: {bazar.name}",
            "bazar": bazar,
            "revision": revision,
            "focus_kind": focus_kind,
            "focus_kind_label": MAP_SECTION_LABELS.get(focus_kind, ""),
            "initial_geojson": revision.geojson,
            "context_geojson": other_bazar_boundaries(bazar),
            "passages": passages,
            "containers": containers,
            "district_tariffs": district_tariffs,
            "google_maps_api_key": os.getenv("GOOGLE_MAPS_BROWSER_API_KEY", "") or os.getenv("GOOGLE_MAPS_API_KEY", ""),
            "save_url": reverse("admin:delivery_market_map_save", args=(bazar.id,)),
            "publish_url": reverse("admin:delivery_market_map_publish", args=(bazar.id,)),
            "changelist_url": reverse("admin:delivery_marketmaprevision_changelist"),
            "opts": self.model._meta,
            "has_view_permission": True,
            "has_change_permission": True,
            "is_popup": False,
        }
        return TemplateResponse(
            request,
            "admin/delivery/marketmaprevision/map_editor.html",
            context,
        )

    def _read_geojson(self, request):
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Не удалось прочитать JSON") from exc
        return payload.get("geojson"), payload.get("base_geojson")

    def save_view(self, request, bazar_id: int):
        bazar = self._bazar(request, bazar_id)
        try:
            submitted, base = self._read_geojson(request)
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
                "revision_id": revision.id,
                "version": revision.version,
                "status": revision.status,
                "updated_at": revision.updated_at.isoformat(),
                "merged": result.merged,
                # Редактор подхватывает проставленные синхронизацией id фигур.
                "geojson": revision.geojson,
            }
        )

    def publish_view(self, request, bazar_id: int):
        bazar = self._bazar(request, bazar_id)
        try:
            submitted, base = self._read_geojson(request)
            result = publish_collaborative_map(
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
        messages.success(request, f"Карта {bazar.name}, версия {revision.version}, опубликована")
        return JsonResponse(
            {
                "ok": True,
                "revision_id": revision.id,
                "version": revision.version,
                "status": revision.status,
                "merged": result.merged,
                "published_at": revision.published_at.isoformat() if revision.published_at else None,
                "geojson": revision.geojson,
            }
        )


class MarketMapSectionAdmin(admin.ModelAdmin):
    change_list_template = "admin/delivery/marketmaprevision/section_change_list.html"
    kind = ""
    section_title = ""
    section_help = ""

    list_display = ("bazar", "version", "status", "updated_at", "published_at", "created_by", "open_editor")
    list_filter = ("status", "bazar")
    search_fields = ("bazar__name",)
    readonly_fields = (
        "bazar",
        "version",
        "status",
        "geojson",
        "created_by",
        "created_at",
        "updated_at",
        "published_at",
    )
    ordering = ("bazar__name", "-version")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return MarketMapRevision.objects.all()

    @admin.display(description="Редактор")
    def open_editor(self, obj: MarketMapRevision):
        url = f'{reverse("admin:delivery_market_map_editor", args=(obj.bazar_id,))}?kind={self.kind}'
        return format_html('<a class="button" href="{}">Открыть раздел</a>', url)

    def changelist_view(self, request, extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context.update(
            {
                "market_map_bazars": Bazar.objects.order_by("name"),
                "market_map_kind": self.kind,
                "market_map_section_title": self.section_title,
                "market_map_section_help": self.section_help,
            }
        )
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(MarketBoundaryMapSection)
class MarketBoundaryMapSectionAdmin(MarketMapSectionAdmin):
    kind = "bazar"
    section_title = "Граница базара"
    section_help = "Создавайте и редактируйте только внешний контур выбранного базара."


@admin.register(MarketDistrictMapSection)
class MarketDistrictMapSectionAdmin(MarketMapSectionAdmin):
    kind = "district"
    section_title = "Границы районов"
    section_help = "Рисуйте контуры районов внутри выбранного базара так же, как границу базара."


@admin.register(MarketPassageMapSection)
class MarketPassageMapSectionAdmin(MarketMapSectionAdmin):
    kind = "passage"
    section_title = "Проходы"
    section_help = "Отдельный раздел для основных линий проходов."


@admin.register(MarketContainerMapSection)
class MarketContainerMapSectionAdmin(MarketMapSectionAdmin):
    kind = "container"
    section_title = "Контейнеры"
    section_help = "Отдельный раздел для прямоугольников контейнеров и привязки к проходам."
