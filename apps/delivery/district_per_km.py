from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.contrib import admin

from .district_catalog import available_district_choices
from .models import Bazar, DeliveryDistrict


class DistrictPerKmAdminForm(forms.ModelForm):
    """Простая форма тарифа: район карты + цена одного километра."""

    class Meta:
        model = DeliveryDistrict
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "name" in self.fields:
            current = ""
            if self.instance and self.instance.pk:
                current = self.instance.name
            elif self.is_bound:
                current = str(self.data.get(self.add_prefix("name")) or "").strip()

            self.fields["name"] = forms.ChoiceField(
                label="Район с карты",
                required=True,
                choices=available_district_choices(
                    current,
                    exclude_configured=not bool(self.instance and self.instance.pk),
                ),
                help_text=(
                    "Выберите район, который уже нарисован и сохранён в разделе «Карты»."
                ),
            )

        if "per_km_price" in self.fields:
            self.fields["per_km_price"].label = "Стоимость за км, сом"
            self.fields["per_km_price"].help_text = (
                "Укажите стоимость одного километра доставки внутри этого района."
            )
            self.fields["per_km_price"].required = True

        if "is_active" in self.fields:
            self.fields["is_active"].label = "Тариф активен"


def _district_per_km_fieldsets(self, request, obj=None):
    return (
        (
            "Тариф района",
            {
                "fields": ("name", "per_km_price", "is_active"),
                "description": (
                    "Выберите район с карты и укажите стоимость 1 км в сомах. "
                    "Цена заказа рассчитывается по длине маршрута."
                ),
            },
        ),
    )


def enable_district_per_km_admin() -> None:
    """Оставить в админке района только цену за километр."""

    district_admin = admin.site._registry.get(DeliveryDistrict)
    if district_admin is None:
        return

    cls = district_admin.__class__
    cls.form = DistrictPerKmAdminForm
    cls.get_fieldsets = _district_per_km_fieldsets
    cls.list_display = ("name", "per_km_price", "is_active")
    cls.list_editable = ("per_km_price", "is_active")
    cls.list_per_page = 30

    current_save_model = cls.save_model
    if getattr(current_save_model, "_safa_per_km_only", False):
        return

    def save_model(self, request, obj, form, change):
        # Старые поля оставляем в БД только для совместимости схемы, но при
        # сохранении тарифа очищаем их, чтобы источником цены был только сом/км.
        obj.fixed_price = None
        obj.base_price = None
        obj.min_fare = None
        return current_save_model(self, request, obj, form, change)

    save_model._safa_per_km_only = True
    cls.save_model = save_model


def per_km_tariff_price(
    tariff: DeliveryDistrict,
    distance_km: Decimal | int | float | str,
) -> int | None:
    """Цена района = стоимость 1 км × длина всего маршрута."""

    if not tariff.is_active or tariff.per_km_price is None:
        return None

    distance = Decimal(str(distance_km or 0))
    cost = Decimal(tariff.per_km_price) * distance
    return int(cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _effective_bazar_fixed_price(bazar: Bazar) -> int | None:
    """Районный тариф больше не имеет фиксированной цены."""

    if bazar.fixed_price is not None:
        return int(bazar.fixed_price)
    if bazar.price_from is not None:
        return int(bazar.price_from)
    return None


def enable_district_per_km_pricing() -> None:
    """Подключить простую районную тарификацию по километражу."""

    from . import map_pricing

    map_pricing.tariff_price = per_km_tariff_price
    Bazar.effective_fixed_price = property(_effective_bazar_fixed_price)
