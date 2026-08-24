from django import forms

from apps.delivery.district_catalog import available_district_choices
from apps.delivery.models import (
    AmanatCampaign,
    Bazar,
    DeliveryDistrict,
    GlobalDeliveryConfig,
)


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


class KYCDecisionForm(forms.Form):
    comment = forms.CharField(
        required=False,
        max_length=2000,
        label="Комментарий",
        widget=forms.Textarea(attrs={"class": "textarea", "rows": 4}),
    )
