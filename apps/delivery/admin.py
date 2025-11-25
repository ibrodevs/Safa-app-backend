from django.contrib import admin

from .models import (
    CourierSegment,
    Shipment,
    ShipmentStop,
    CourierPosition,
)


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

    Поля, связанные с контейнерами/базарами, убраны.
    Позиция выставляется автоматически (0, 1, 2...) в save_related().
    """
    model = ShipmentStop
    extra = 0
    # никаких autocomplete по контейнерам
    # показываем только служебные поля маршрута
    fields = ("position",)
    ordering = ("position",)


@admin.action(description="Пересчитать стоимость")
def reestimate_action(modeladmin, request, queryset):
    # убрали prefetch_related("stops__container"), т.к. контейнеров больше нет
    for s in queryset.select_related("segment").prefetch_related("stops"):
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
    search_fields = ("title", "client__first_name", "client__phone_number")
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
        stops = list(shipment.stops.order_by("position", "id"))
        changed = False
        for idx, stop in enumerate(stops):
            if stop.position != idx:
                stop.position = idx
                stop.save(update_fields=["position"])
                changed = True

        if changed:
            shipment.estimate()
            shipment.save(update_fields=["distance_km", "estimated_fare"])
