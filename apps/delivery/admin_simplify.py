from __future__ import annotations

from django import forms
from django.contrib import admin

from .district_catalog import available_district_choices
from .map_models import MarketMapRevision
from .models import Bazar, Container, DeliveryDistrict, Passage


def _configure_field(form: forms.ModelForm, name: str, *, label: str | None = None, help_text: str | None = None) -> None:
    """Configure a field only when Django included it in the current admin form.

    ModelAdmin.get_form() narrows ModelForm fields to the active fieldsets. Add
    forms intentionally hide legacy/advanced fields, so touching them
    unconditionally raises KeyError and turns the admin page into HTTP 500.
    """
    field = form.fields.get(name)
    if field is None:
        return
    if label is not None:
        field.label = label
    if help_text is not None:
        field.help_text = help_text


class SimpleDistrictAdminForm(forms.ModelForm):
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
                    "Список формируется из районов, нарисованных и сохранённых в разделе «Карты». "
                    "Если нужного района нет — сначала создайте его на карте и нажмите «Сохранить»."
                ),
            )

        _configure_field(
            self,
            "fixed_price",
            label="Фиксированная цена, сом",
            help_text="Цена доставки внутри выбранного района в сомах. Если не нужна — оставьте пустой.",
        )
        _configure_field(self, "is_active", label="Тариф активен")
        _configure_field(
            self,
            "base_price",
            label="Базовая стоимость, сом",
            help_text="Базовая часть тарифа в сомах. Обычно менять не нужно.",
        )
        _configure_field(
            self,
            "per_km_price",
            label="Стоимость за км, сом",
            help_text="Дополнительная стоимость за каждый километр в сомах.",
        )
        _configure_field(
            self,
            "min_fare",
            label="Минимальная цена, сом",
            help_text="Минимальная стоимость доставки по этому тарифу в сомах.",
        )


class SimpleBazarAdminForm(forms.ModelForm):
    class Meta:
        model = Bazar
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configure_field(
            self,
            "name",
            label="Название базара",
            help_text="Например: Дордой, Орто-Сай, Ошский рынок.",
        )
        _configure_field(
            self,
            "district_tariff",
            label="Тариф района",
            help_text="Выберите тариф района, который применяется к базару, если у базара нет своей цены.",
        )
        _configure_field(
            self,
            "fixed_price",
            label="Своя цена базара, сом",
            help_text="Необязательно. Если пусто — используется цена выбранного тарифа района.",
        )
        _configure_field(
            self,
            "district",
            label="Старое название района",
            help_text="Служебное поле совместимости. Обычно менять не нужно.",
        )
        _configure_field(
            self,
            "price_from",
            help_text="Старое поле тарифа. Оставьте как есть, если не знаете зачем оно нужно.",
        )
        _configure_field(
            self,
            "price_to",
            help_text="Старое поле тарифа. Оставьте как есть, если не знаете зачем оно нужно.",
        )


class SimplePassageAdminForm(forms.ModelForm):
    class Meta:
        model = Passage
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configure_field(
            self,
            "bazar",
            label="Базар",
            help_text="Сначала выберите базар, внутри которого находится проход.",
        )
        _configure_field(
            self,
            "number",
            label="Название или номер прохода",
            help_text="Например: 1, 7А или Центральный проход.",
        )


class SimpleContainerAdminForm(forms.ModelForm):
    class Meta:
        model = Container
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configure_field(
            self,
            "passage",
            label="Проход",
            help_text="Выберите проход. Базар определится автоматически через проход.",
        )
        _configure_field(
            self,
            "number",
            label="Номер контейнера",
            help_text="Например: 101, A-12 или 4/7.",
        )
        _configure_field(
            self,
            "title",
            label="Название (необязательно)",
            help_text="Можно оставить пустым, если достаточно номера контейнера.",
        )
        _configure_field(
            self,
            "lat",
            label="Широта",
            help_text="Координата контейнера. Проще создавать контейнеры через редактор карты.",
        )
        _configure_field(
            self,
            "lon",
            label="Долгота",
            help_text="Координата контейнера. Проще создавать контейнеры через редактор карты.",
        )
        _configure_field(self, "is_active", label="Контейнер активен")


def _district_fieldsets(self, request, obj=None):
    sections = [
        (
            "Создание тарифа района",
            {
                "fields": ("name", "fixed_price", "is_active"),
                "description": (
                    "1. Выберите район, который уже создан на карте. "
                    "2. Укажите стоимость доставки в сомах. "
                    "3. Сохраните тариф."
                ),
            },
        )
    ]
    if obj is not None:
        sections.append(
            (
                "Дополнительные тарифы",
                {
                    "fields": ("base_price", "per_km_price", "min_fare"),
                    "classes": ("collapse",),
                    "description": "Открывайте этот блок только если используется расчёт по километражу. Все суммы указаны в сомах.",
                },
            )
        )
    return tuple(sections)


def _bazar_fieldsets(self, request, obj=None):
    sections = [
        (
            "Создание базара",
            {
                "fields": ("name", "district_tariff", "fixed_price"),
                "description": "1. Укажите название. 2. При необходимости выберите тариф района. 3. При необходимости задайте отдельную цену. Границу базара рисуйте в разделе карты.",
            },
        )
    ]
    if obj is not None:
        sections.extend(
            [
                (
                    "Старые параметры тарифа",
                    {
                        "fields": ("district", "price_from", "price_to"),
                        "classes": ("collapse",),
                        "description": "Служебные поля старой версии. Обычно их менять не нужно.",
                    },
                ),
                (
                    "Старые координаты границы",
                    {
                        "fields": ("top_left_lat", "top_left_lon", "bottom_right_lat", "bottom_right_lon"),
                        "classes": ("collapse",),
                        "description": "Границу лучше редактировать визуально в разделе карты.",
                    },
                ),
            ]
        )
    return tuple(sections)


def _passage_fieldsets(self, request, obj=None):
    return (
        (
            "Проход",
            {
                "fields": ("bazar", "number"),
                "description": "Выберите базар и укажите понятное название или номер прохода. Если проход рисуется на карте, он также синхронизируется с этим списком.",
            },
        ),
    )


def _container_fieldsets(self, request, obj=None):
    sections = [
        (
            "Контейнер",
            {
                "fields": ("passage", "number", "title"),
                "description": "Главное — выбрать проход и указать номер контейнера. Базар определяется автоматически.",
            },
        ),
        (
            "Расположение",
            {
                "fields": ("lat", "lon"),
                "description": "Если возможно, создавайте контейнер через редактор карты — координаты заполнятся автоматически.",
            },
        ),
    ]
    if obj is not None:
        sections.append(("Статус", {"fields": ("is_active",)}))
    return tuple(sections)


def _bazar_save_model(self, request, obj, form, change):
    # Один источник правды для обычного администратора: выбранный район.
    # Старое строковое поле оставляем синхронизированным для legacy-кода и GeoJSON.
    if obj.district_tariff_id:
        obj.district = obj.district_tariff.name
    return super(self.__class__, self).save_model(request, obj, form, change)


def _hide_technical_map_model(self, request):
    # Ревизии/GeoJSON остаются доступны редактору карты по URL, но не засоряют
    # главное меню отдельной технической сущностью.
    return {}


def simplify_delivery_admin() -> None:
    admin.site.site_header = "Safa — управление"
    admin.site.site_title = "Safa Admin"
    admin.site.index_title = "Управление Safa"

    district_admin = admin.site._registry.get(DeliveryDistrict)
    if district_admin:
        cls = district_admin.__class__
        cls.form = SimpleDistrictAdminForm
        cls.get_fieldsets = _district_fieldsets
        cls.list_display = ("name", "fixed_price", "is_active")
        cls.list_editable = ("fixed_price", "is_active")
        cls.list_per_page = 30

    bazar_admin = admin.site._registry.get(Bazar)
    if bazar_admin:
        cls = bazar_admin.__class__
        cls.form = SimpleBazarAdminForm
        cls.get_fieldsets = _bazar_fieldsets
        cls.list_display = ("name", "district_tariff", "fixed_price")
        cls.list_filter = ("district_tariff",)
        cls.list_per_page = 30

        original_save_model = cls.save_model

        def save_model(self, request, obj, form, change):
            if obj.district_tariff_id:
                obj.district = obj.district_tariff.name
            return original_save_model(self, request, obj, form, change)

        cls.save_model = save_model

    passage_admin = admin.site._registry.get(Passage)
    if passage_admin:
        cls = passage_admin.__class__
        cls.form = SimplePassageAdminForm
        cls.get_fieldsets = _passage_fieldsets
        cls.list_display = ("number", "bazar")
        cls.list_per_page = 40

    container_admin = admin.site._registry.get(Container)
    if container_admin:
        cls = container_admin.__class__
        cls.form = SimpleContainerAdminForm
        cls.get_fieldsets = _container_fieldsets
        cls.list_display = ("number", "passage", "bazar_name", "title", "is_active")
        cls.list_per_page = 50

    map_admin = admin.site._registry.get(MarketMapRevision)
    if map_admin:
        map_admin.__class__.get_model_perms = _hide_technical_map_model
