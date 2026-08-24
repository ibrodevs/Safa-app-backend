from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.delivery.district_catalog import available_district_choices
from apps.delivery.models import (
    AmanatCampaign,
    AmanatCategory,
    Bazar,
    DeliveryDistrict,
    GlobalDeliveryConfig,
    Shipment,
    ShipmentStop,
)
from apps.users.models import User


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "checkbox")
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "textarea")
                field.widget.attrs.setdefault("rows", 4)
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "select")
            else:
                field.widget.attrs.setdefault("class", "input")


class GlobalTariffForm(StyledModelForm):
    class Meta:
        model = GlobalDeliveryConfig
        fields = ("base_price", "per_km_price", "min_fare")
        labels = {
            "base_price": "Базовая стоимость",
            "per_km_price": "Стоимость за км",
            "min_fare": "Минимальная стоимость",
        }


class DistrictTariffForm(StyledModelForm):
    class Meta:
        model = DeliveryDistrict
        fields = ("name", "per_km_price", "is_active")
        labels = {
            "name": "Район с карты",
            "per_km_price": "Стоимость за км, сом",
            "is_active": "Тариф активен",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.name if self.instance and self.instance.pk else ""
        self.fields["name"] = forms.ChoiceField(
            choices=available_district_choices(
                current,
                exclude_configured=not bool(self.instance and self.instance.pk),
            ),
            label="Район с карты",
            widget=forms.Select(attrs={"class": "select"}),
        )
        self.fields["per_km_price"].required = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.fixed_price = None
        instance.base_price = None
        instance.min_fare = None
        if commit:
            instance.save()
        return instance


class BazarTariffForm(StyledModelForm):
    class Meta:
        model = Bazar
        fields = ("district_tariff", "fixed_price")
        labels = {
            "district_tariff": "Тариф района",
            "fixed_price": "Собственная фиксированная цена",
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.district_tariff_id:
            instance.district = instance.district_tariff.name
        if commit:
            instance.save()
        return instance


class BazarPanelForm(StyledModelForm):
    class Meta:
        model = Bazar
        fields = ("name", "district_tariff", "fixed_price")
        labels = {
            "name": "Название базара",
            "district_tariff": "Тариф района",
            "fixed_price": "Собственная фиксированная цена",
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.district_tariff_id:
            instance.district = instance.district_tariff.name
        if commit:
            instance.save()
        return instance


class AmanatCampaignForm(StyledModelForm):
    class Meta:
        model = AmanatCampaign
        fields = (
            "category",
            "title",
            "short_title",
            "description",
            "goal",
            "cover_image",
            "needed_amount",
            "collected_amount_manual",
            "safa_amount",
            "helpers_count_manual",
            "ends_at",
            "status",
            "is_featured",
            "sort_order",
        )
        widgets = {"ends_at": forms.DateInput(attrs={"type": "date"})}


class AmanatCategoryForm(StyledModelForm):
    class Meta:
        model = AmanatCategory
        fields = ("name", "slug", "sort_order", "is_active")
        labels = {
            "name": "Название",
            "slug": "Код категории",
            "sort_order": "Порядок",
            "is_active": "Категория активна",
        }


class KYCDecisionForm(forms.Form):
    comment = forms.CharField(
        required=False,
        max_length=2000,
        label="Комментарий",
        widget=forms.Textarea(attrs={"class": "textarea", "rows": 4}),
    )


class PanelUserForm(StyledModelForm):
    class Meta:
        model = User
        fields = (
            "phone_number",
            "first_name",
            "role",
            "specialist_type",
            "city",
            "avatar",
            "is_verify",
            "is_active",
        )
        labels = {
            "phone_number": "Телефон",
            "first_name": "Имя",
            "role": "Роль",
            "specialist_type": "Специализация",
            "city": "Город",
            "avatar": "Аватар",
            "is_verify": "Телефон подтверждён",
            "is_active": "Доступ активен",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("role") != User.Roles.CARRIER:
            cleaned["specialist_type"] = None
        elif not cleaned.get("specialist_type"):
            self.add_error("specialist_type", "Выберите специализацию.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.pk:
            user.set_unusable_password()
        if commit:
            user.save()
        return user


class ShipmentPanelForm(StyledModelForm):
    class Meta:
        model = Shipment
        fields = (
            "title",
            "service_type",
            "description",
            "client",
            "carrier",
            "status",
            "is_paid",
            "final_fare",
        )
        labels = {
            "title": "Название заказа",
            "service_type": "Тип услуги",
            "description": "Описание",
            "client": "Клиент",
            "carrier": "Специалист",
            "status": "Статус",
            "is_paid": "Заказ оплачен",
            "final_fare": "Итоговая стоимость",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = User.objects.filter(
            role=User.Roles.CLIENT, is_staff=False
        ).order_by("first_name", "phone_number")
        self.fields["carrier"].queryset = User.objects.filter(
            role=User.Roles.CARRIER, is_staff=False
        ).order_by("first_name", "phone_number")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == Shipment.Status.COMPLETED and not cleaned.get("is_paid"):
            self.add_error("is_paid", "Завершённый заказ должен быть оплачен.")
        return cleaned


class ShipmentStopPanelForm(StyledModelForm):
    class Meta:
        model = ShipmentStop
        fields = ("container", "title", "lat", "lon")
        labels = {
            "container": "Контейнер на карте",
            "title": "Адрес или название точки",
            "lat": "Широта",
            "lon": "Долгота",
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        has_data = any(
            cleaned.get(name) not in (None, "")
            for name in ("container", "title", "lat", "lon")
        )
        if not has_data and not self.instance.pk:
            return cleaned
        if not cleaned.get("container"):
            if not (cleaned.get("title") or "").strip():
                self.add_error("title", "Укажите название или выберите контейнер.")
            if cleaned.get("lat") is None or cleaned.get("lon") is None:
                raise forms.ValidationError("Для ручной точки укажите широту и долготу.")
        return cleaned


class BaseShipmentStopFormSet(BaseInlineFormSet):
    ordering_widget = forms.HiddenInput

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active = []
        for form in self.forms:
            data = form.cleaned_data
            has_data = form.instance.pk or any(
                data.get(name) not in (None, "")
                for name in ("container", "title", "lat", "lon")
            )
            if has_data and not data.get("DELETE"):
                active.append(form)
        if len(active) < 2:
            raise forms.ValidationError("Маршрут должен содержать минимум две точки.")
        if len(active) > 30:
            raise forms.ValidationError("В маршруте может быть не больше 30 точек.")


ShipmentStopFormSet = inlineformset_factory(
    Shipment,
    ShipmentStop,
    form=ShipmentStopPanelForm,
    formset=BaseShipmentStopFormSet,
    extra=2,
    can_delete=True,
    can_order=True,
)
