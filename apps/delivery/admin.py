# apps/delivery/admin.py
from django.contrib import admin

from .models import (
    Bazar,
    Container,
    CourierSegment,
    Shipment,
    ShipmentStop,
    CourierPosition,
)


@admin.register(Bazar)
class BazarAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "bazar", "number", "passage", "latitude", "longitude")
    list_filter = ("bazar",)
    search_fields = ("title", "number", "passage", "bazar__name")
    ordering = ("bazar__name", "title")


@admin.register(CourierSegment)
class CourierSegmentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "slug", "is_active",
        "base_price", "per_km_price", "min_fare",
        "fragile_pct", "size_s_multiplier", "size_m_multiplier", "size_l_multiplier",
        "per_unit",
    )
    list_editable = ("is_active",)
    search_fields = ("name", "slug")
    list_filter = ("is_active",)
    ordering = ("order", "name")


class ShipmentStopInline(admin.TabularInline):
    """
    Остановки маршрута в админке.
    Позицию руками не трогаем — она проставится автоматически.
    """
    model = ShipmentStop
    extra = 0
    autocomplete_fields = ("container",)
    fields = ("container",)          # НЕ показываем поле position
    ordering = ("position",)         # показываем в порядке позиции
    # position остаётся в модели, просто скрыта из формы


@admin.action(description="Пересчитать стоимость")
def reestimate_action(modeladmin, request, queryset):
    for s in queryset.select_related("segment").prefetch_related("stops__container"):
        s.estimate()
        s.save(update_fields=["distance_km", "estimated_fare"])


@admin.action(description="Завершить и зафиксировать цену")
def complete_action(modeladmin, request, queryset):
    for s in queryset:
        s.status = Shipment.Status.COMPLETED
        s.finalize()
        s.save(update_fields=["status", "final_fare"])


@admin.action(description="Отменить")
def cancel_action(modeladmin, request, queryset):
    for s in queryset:
        s.status = Shipment.Status.CANCELED
        s.save(update_fields=["status"])


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "client", "carrier", "segment",
        "status", "size", "fragile",
        "distance_km", "estimated_fare", "final_fare",
        "created_at",
    )
    list_filter = ("status", "size", "fragile", "segment")
    search_fields = ("title", "client__first_name", "client__last_name", "client__phone_number")
    date_hierarchy = "created_at"
    readonly_fields = (
        "distance_km", "estimated_fare", "final_fare",
        "current_stop_index", "eta_to_next_min", "created_at",
    )
    autocomplete_fields = ("client", "carrier", "segment")
    inlines = (ShipmentStopInline,)
    actions = (reestimate_action, complete_action, cancel_action)
    list_select_related = ("client", "carrier", "segment")
    ordering = ("-created_at",)

    fieldsets = (
        ("Основное", {
            "fields": ("title", "description", "client", "carrier", "status")
        }),
        ("Тариф", {
            "fields": ("segment", "size", "quantity", "fragile")
        }),
        ("Расчёт", {
            "fields": ("distance_km", "estimated_fare", "final_fare", "current_stop_index", "eta_to_next_min")
        }),
        ("Служебное", {
            "fields": ("created_at",),
        }),
    )

    def save_related(self, request, form, formsets, change):
        """
        После сохранения инлайнов пере-нумеровываем остановки:
        position = 0, 1, 2, ... по порядку.
        """
        super().save_related(request, form, formsets, change)

        shipment = form.instance
        # Берём все остановки этого шипмента и жёстко даём им позиции 0..n-1
        stops = list(shipment.stops.order_by("position", "id"))
        changed = False
        for idx, stop in enumerate(stops):
            if stop.position != idx:
                stop.position = idx
                stop.save(update_fields=["position"])
                changed = True

        # Если нужно, можно тут же пересчитать маршрут/цену:
        if changed:
            shipment.estimate()
            shipment.save(update_fields=["distance_km", "estimated_fare"])
