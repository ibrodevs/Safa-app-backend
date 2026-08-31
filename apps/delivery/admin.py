from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError

from .models import (
    AmanatCampaign,
    AmanatCategory,
    AmanatDonation,
    AmanatDocument,
    GlobalDeliveryConfig,
    Shipment,
    ShipmentStop,
    CourierPosition,
    Bazar,
    DeliveryDistrict,
    Passage,
    Container,
    SupportContact,
)
from .map_cleanup import delete_bazar_with_map, delete_passage_with_containers
from .map_models import MarketMapRevision
from .operations import (
    cancel_shipment,
    normalize_shipment_stops,
    reestimate_shipment,
    sync_shipment_admin_state,
)


def available_district_choices(current: str | None = None) -> list[tuple[str, str]]:
    names: set[str] = set()

    for name in Bazar.objects.exclude(district="").values_list("district", flat=True).distinct():
        clean = (name or "").strip()
        if clean:
            names.add(clean)

    revisions = MarketMapRevision.objects.filter(status=MarketMapRevision.Status.PUBLISHED).only("geojson")
    for revision in revisions:
        for feature in (revision.geojson or {}).get("features", []):
            properties = feature.get("properties") or {}
            if properties.get("kind") != "district":
                continue
            clean = str(properties.get("name") or "").strip()
            if clean:
                names.add(clean)

    clean_current = (current or "").strip()
    if clean_current:
        names.add(clean_current)

    return [("", "---------"), *[(name, name) for name in sorted(names)]]


class DeliveryDistrictAdminForm(forms.ModelForm):
    class Meta:
        model = DeliveryDistrict
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.name if self.instance and self.instance.pk else self.data.get("name")
        self.fields["name"] = forms.ChoiceField(
            label=self.fields["name"].label,
            required=True,
            choices=available_district_choices(current),
            help_text="Выберите район из уже созданных районов базаров или опубликованной карты.",
        )


@admin.register(DeliveryDistrict)
class DeliveryDistrictAdmin(admin.ModelAdmin):
    form = DeliveryDistrictAdminForm
    list_display = ("id", "name", "fixed_price", "base_price", "per_km_price", "min_fare", "is_active")
    list_editable = ("fixed_price", "is_active")
    search_fields = ("name",)
    list_filter = ("is_active",)
    ordering = ("name",)
    fieldsets = (
        ("Район", {"fields": ("name", "is_active")}),
        (
            "Фиксированная цена",
            {
                "fields": ("fixed_price",),
                "description": "Используется для заказов, где точки находятся внутри базаров этого района, если у самого базара не задана своя цена.",
            },
        ),
        ("Километраж", {"fields": ("base_price", "per_km_price", "min_fare")}),
    )


@admin.register(Bazar)
class BazarAdmin(admin.ModelAdmin):
    """Базар удаляется вместе со своей картой, проходами и контейнерами."""

    list_display = ("id", "name", "district", "district_tariff", "fixed_price", "price_from", "price_to")
    search_fields = ("name", "district", "district_tariff__name")
    list_filter = ("district", "district_tariff")
    ordering = ("name",)
    autocomplete_fields = ("district_tariff",)
    fields = (
        "name",
        "district",
        "district_tariff",
        "fixed_price",
        "price_from",
        "price_to",
        "top_left_lat",
        "top_left_lon",
        "bottom_right_lat",
        "bottom_right_lon",
    )

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs,
            request,
        )
        # Карта, проходы и контейнеры — части базара, они удаляются вместе с ним.
        # Остановки посылок не удаляются: у них останутся координаты и подпись.
        return deleted_objects, model_count, set(), []

    def delete_model(self, request, obj):
        delete_bazar_with_map(obj)

    def delete_queryset(self, request, queryset):
        for bazar in queryset:
            delete_bazar_with_map(bazar)


@admin.register(Passage)
class PassageAdmin(admin.ModelAdmin):
    """Проход удаляется вместе со своими контейнерами."""

    list_display = ("id", "number", "district", "angle_display", "bazar")
    search_fields = ("number", "district", "bazar__name")
    list_filter = ("bazar", "district")
    autocomplete_fields = ("bazar",)
    fields = ("bazar", "district", "number", "angle")
    ordering = ("bazar__name", "district", "number")

    @admin.display(description="Угол наклона", ordering="angle")
    def angle_display(self, obj: Passage) -> str:
        return obj.angle_label

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        return deleted_objects, model_count, set(), []

    def delete_model(self, request, obj):
        delete_passage_with_containers(obj)

    def delete_queryset(self, request, queryset):
        for passage in queryset:
            delete_passage_with_containers(passage)


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("id", "number", "passage", "bazar_name", "title", "lat", "lon", "is_active")
    list_filter = ("is_active", "passage__bazar")
    search_fields = (
        "number",
        "title",
        "passage__number",
        "passage__bazar__name",
    )
    autocomplete_fields = ("passage",)
    fields = ("passage", "number", "title", "lat", "lon", "is_active")
    ordering = ("passage__bazar__name", "passage__number", "number")

    @admin.display(description="Базар")
    def bazar_name(self, obj: Container) -> str:
        return obj.passage.bazar.name


@admin.register(AmanatCategory)
class AmanatCategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")
    ordering = ("sort_order", "name")


class AmanatDocumentInline(admin.TabularInline):
    model = AmanatDocument
    extra = 1
    fields = ("title", "file", "description", "sort_order", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("sort_order", "-created_at")


class AmanatDonationInline(admin.TabularInline):
    model = AmanatDonation
    extra = 0
    fields = ("donor", "donor_label", "amount", "status", "is_anonymous", "created_at", "paid_at")
    readonly_fields = ("created_at", "paid_at")
    autocomplete_fields = ("donor",)
    ordering = ("-created_at",)


@admin.register(AmanatCampaign)
class AmanatCampaignAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "category",
        "status",
        "needed_amount",
        "collected_amount_display",
        "helpers_count_display",
        "is_featured",
        "sort_order",
    )
    list_filter = ("status", "is_featured", "category")
    list_editable = ("status", "is_featured", "sort_order")
    search_fields = ("title", "short_title", "description")
    autocomplete_fields = ("category",)
    readonly_fields = (
        "safa_amount",
        "created_at",
        "updated_at",
        "collected_amount_display",
        "helpers_count_display",
    )
    inlines = (AmanatDocumentInline, AmanatDonationInline)
    ordering = ("sort_order", "-created_at")
    fieldsets = (
        ("Основное", {"fields": ("category", "title", "short_title", "description", "goal", "cover_image")}),
        (
            "Суммы",
            {
                "fields": (
                    "needed_amount",
                    "collected_amount_manual",
                    "safa_amount",
                    "helpers_count_manual",
                )
            },
        ),
        ("Публикация", {"fields": ("status", "is_featured", "sort_order", "ends_at")}),
        ("Служебное", {"fields": ("collected_amount_display", "helpers_count_display", "created_at", "updated_at")}),
    )

    @admin.display(description="Собрано")
    def collected_amount_display(self, obj: AmanatCampaign) -> int:
        return obj.collected_amount

    @admin.display(description="Помогли")
    def helpers_count_display(self, obj: AmanatCampaign) -> int:
        return obj.helpers_count


@admin.register(AmanatDocument)
class AmanatDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "campaign", "file", "sort_order", "created_at")
    list_filter = ("campaign",)
    search_fields = ("title", "description", "campaign__title")
    autocomplete_fields = ("campaign",)
    readonly_fields = ("created_at",)
    ordering = ("campaign", "sort_order", "-created_at")


@admin.register(AmanatDonation)
class AmanatDonationAdmin(admin.ModelAdmin):
    list_display = ("id", "campaign", "donor", "amount", "status", "is_anonymous", "created_at", "paid_at")
    list_filter = ("status", "is_anonymous", "campaign")
    search_fields = ("campaign__title", "donor__phone_number", "donor_label")
    autocomplete_fields = ("campaign", "donor")
    readonly_fields = ("created_at", "paid_at")
    ordering = ("-created_at",)


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
        try:
            reestimate_shipment(s, protect_terminal=False, emit_events=False)
        except ValueError:
            continue


@admin.action(description="Завершить оплаченные заказы")
def complete_action(modeladmin, request, queryset):
    for s in queryset:
        if not s.is_paid or s.status != Shipment.Status.AWAITING_PAYMENT:
            continue
        attempt = s.payment_attempts.filter(status="SUCCEEDED").order_by("-updated_at").first()
        if not attempt:
            continue
        from apps.payments.settlement import complete_paid_shipment

        complete_paid_shipment(shipment=s, payment_attempt=attempt)


@admin.action(description="Отменить")
def cancel_action(modeladmin, request, queryset):
    for s in queryset:
        try:
            cancel_shipment(s, protect_terminal=False, emit_events=False)
        except ValueError:
            continue


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "client",
        "carrier",
        "status",
        "is_paid",
        "service_type",
        "is_demo",
        "distance_km",
        "estimated_fare",
        "final_fare",
        "created_at",
    )
    list_filter = ("status", "is_paid", "service_type", "is_demo")
    search_fields = ("title", "client__first_name", "client__phone_number")
    date_hierarchy = "created_at"
    readonly_fields = (
        "distance_km",
        "estimated_fare",
        "final_fare",
        "current_stop_index",
        "eta_to_next_min",
        "paid_at",
        "work_completed_at",
        "finished_at",
        "created_at",
    )
    autocomplete_fields = ("client", "carrier")
    inlines = (ShipmentStopInline,)
    actions = (reestimate_action, complete_action, cancel_action)
    list_select_related = ("client", "carrier")
    ordering = ("-created_at",)

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "title",
                    "service_type",
                    "description",
                    "client",
                    "carrier",
                    "is_demo",
                )
            },
        ),
        (
            "Статус и оплата",
            {
                "fields": (
                    "status",
                    "is_paid",
                    "paid_at",
                    "work_completed_at",
                    "finished_at",
                ),
                "description": (
                    "Администратор может изменить статус вручную. Для статуса "
                    "«Завершён» обязательно отметьте «Оплачено»."
                ),
            },
        ),
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

    def save_model(self, request, obj, form, change):
        sync_shipment_admin_state(obj)
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        """После сохранения инлайнов пере-нумеровываем остановки: position = 0,1,2,..."""
        super().save_related(request, form, formsets, change)

        normalize_shipment_stops(form.instance)


@admin.register(CourierPosition)
class CourierPositionAdmin(admin.ModelAdmin):
    list_display = ("user", "lat", "lon", "updated_at")
    search_fields = ("user__phone_number", "user__first_name")
    autocomplete_fields = ("user",)


@admin.register(SupportContact)
class SupportContactAdmin(admin.ModelAdmin):
    list_display = ("phone", "telegram", "whatsapp", "working_hours", "is_active", "updated_at")
    list_editable = ("is_active",)
