from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError

from .models import (
    GlobalDeliveryConfig,
    Shipment,
    ShipmentStop,
    CourierPosition,
    Bazar,
    Passage,
    Container,
)


@admin.register(Bazar)
class BazarAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(Passage)
class PassageAdmin(admin.ModelAdmin):
    list_display = ("id", "number", "bazar")
    search_fields = ("number", "bazar__name")
    list_filter = ("bazar",)
    autocomplete_fields = ("bazar",)
    ordering = ("bazar__name", "number")


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("id", "number", "passage", "bazar_name", "title", "is_active")
    list_filter = ("is_active", "passage__bazar")
    search_fields = (
        "number",
        "title",
        "passage__number",
        "passage__bazar__name",
    )
    autocomplete_fields = ("passage",)
    ordering = ("passage__bazar__name", "passage__number", "number")

    @admin.display(description="Базар")
    def bazar_name(self, obj: Container) -> str:
        return obj.passage.bazar.name


@admin.register(GlobalDeliveryConfig)
class GlobalDeliveryConfigAdmin(admin.ModelAdmin):
    list_display = ("base_price", "per_km_price", "min_fare", "updated_at")
    
    fieldsets = (
        ("Настройки тарификации", {
            "fields": ("base_price", "per_km_price", "min_fare"),
            "description": "Эти значения используются для расчета стоимости всех новых заказов."
        }),
        ("Системная информация", {
            "fields": ("updated_at",),
            "classes": ("collapse",)
        }),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        if GlobalDeliveryConfig.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False


class ShipmentStopInlineForm(forms.ModelForm):
    class Meta:
        model = ShipmentStop
        fields = ("position", "container", "title", "lat", "lon")

    def clean(self):
        cleaned = super().clean()
        container = cleaned.get("container")
        title = (cleaned.get("title") or "").strip()
        lat = cleaned.get("lat")
        lon = cleaned.get("lon")

        if container is None:
            # Ручной режим — нужно всё.
            if not title:
                raise ValidationError("Заполни title или выбери контейнер.")
            if lat is None or lon is None:
                raise ValidationError("Заполни lat/lon или выбери контейнер.")

        return cleaned


class ShipmentStopInline(admin.TabularInline):
    """Остановки маршрута в админке.

    Теперь можно:
    - выбрать контейнер (с автозаполнением lat/lon)
    - или заполнить координаты вручную

    position всё так же выставляется автоматически (0,1,2...).
    """

    model = ShipmentStop
    form = ShipmentStopInlineForm
    extra = 0
    fields = ("position", "container", "title", "lat", "lon")
    autocomplete_fields = ("container",)
    ordering = ("position",)


@admin.action(description="Пересчитать стоимость")
def reestimate_action(modeladmin, request, queryset):
    for s in queryset.prefetch_related("stops"):
        # Если не все точки заполнены координатами, estimate() даст 0км — это ок.
        s.estimate()
        s.save(update_fields=["distance_km", "estimated_fare"])


@admin.action(description="Завершить и зафиксировать цену")
def complete_action(modeladmin, request, queryset):
    for s in queryset:
        s.status = Shipment.Status.COMPLETED
        s.finalize()
        s.save(update_fields=["status", "final_fare", "finished_at"])


@admin.action(description="Отменить")
def cancel_action(modeladmin, request, queryset):
    for s in queryset:
        s.status = Shipment.Status.CANCELED
        s.save(update_fields=["status"])


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "client",
        "carrier",
        "status",
        "distance_km",
        "estimated_fare",
        "final_fare",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("title", "client__first_name", "client__phone_number")
    date_hierarchy = "created_at"
    readonly_fields = (
        "distance_km",
        "estimated_fare",
        "final_fare",
        "current_stop_index",
        "eta_to_next_min",
        "created_at",
    )
    autocomplete_fields = ("client", "carrier")
    inlines = (ShipmentStopInline,)
    actions = (reestimate_action, complete_action, cancel_action)
    list_select_related = ("client", "carrier")
    ordering = ("-created_at",)

    fieldsets = (
        ("Основное", {"fields": ("title", "description", "client", "carrier", "status")}),
        (
            "Расчёт",
            {
                "fields": (
                    "distance_km",
                    "estimated_fare",
                    "final_fare",
                    "current_stop_index",
                    "eta_to_next_min",
                )
            },
        ),
        ("Служебное", {"fields": ("created_at",)}),
    )

    def save_related(self, request, form, formsets, change):
        """После сохранения инлайнов пере-нумеровываем остановки: position = 0,1,2,..."""
        super().save_related(request, form, formsets, change)

        shipment = form.instance
        stops = list(shipment.stops.order_by("position", "id"))

        # 1) позиция строго по порядку
        for idx, stop in enumerate(stops):
            if stop.position != idx:
                ShipmentStop.objects.filter(pk=stop.pk).update(position=idx)

        # 2) пересчёт стоимости (если есть минимум 2 точки)
        # estimate() безопасен даже если координаты ещё не заполнены (даст 0км)
        shipment.estimate()
        shipment.save(update_fields=["distance_km", "estimated_fare"])


@admin.register(CourierPosition)
class CourierPositionAdmin(admin.ModelAdmin):
    list_display = ("user", "lat", "lon", "updated_at")
    search_fields = ("user__phone_number", "user__first_name")
    autocomplete_fields = ("user",)
