from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.delivery.district_catalog import available_district_choices
from apps.delivery.models import (
    AmanatCampaign,
    AmanatCategory,
    Bazar,
    Container,
    DeliveryDistrict,
    GlobalDeliveryConfig,
    Passage,
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
        fields = ("name", "per_km_price", "min_fare", "is_active")
        labels = {
            "name": "Район с карты",
            "per_km_price": "Стоимость за км, сом",
            "min_fare": "Минимальная стоимость, сом",
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
        self.fields["min_fare"].required = False
        self.fields["min_fare"].help_text = "Необязательно"

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.fixed_price = None
        instance.base_price = None
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


class DistrictPanelForm(StyledModelForm):
    class Meta:
        model = DeliveryDistrict
        fields = ("name", "per_km_price", "min_fare", "is_active")
        labels = {
            "name": "Название района",
            "per_km_price": "Стоимость за км, сом",
            "min_fare": "Минимальная стоимость, сом",
            "is_active": "Район активен",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["per_km_price"].required = True
        self.fields["min_fare"].required = False
        self.fields["min_fare"].help_text = "Необязательно"

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.fixed_price = None
        instance.base_price = None
        if commit:
            instance.save()
        return instance


class PassagePanelForm(StyledModelForm):
    class Meta:
        model = Passage
        fields = ("bazar", "district", "number", "angle")
        labels = {
            "bazar": "Базар",
            "district": "Район",
            "number": "Название или номер прохода",
            "angle": "Угол наклона, °",
        }
        help_texts = {
            "district": (
                "Название района с карты базара. Номера проходов уникальны внутри "
                "района, поэтому «1 проход» может быть в каждом районе. "
                "Оставьте пустым, если проход не входит ни в один район."
            ),
            "angle": (
                "Считается автоматически по линии прохода на карте: 0° — на восток, "
                "дальше по часовой стрелке. Под этим же углом удобно создавать и "
                "дублировать контейнеры вдоль прохода."
            ),
        }


class ContainerPanelForm(StyledModelForm):
    class Meta:
        model = Container
        fields = ("passage", "number", "title", "lat", "lon", "is_active")
        labels = {
            "passage": "Проход",
            "number": "Номер контейнера",
            "title": "Название или примечание",
            "lat": "Широта",
            "lon": "Долгота",
            "is_active": "Контейнер активен",
        }


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
        labels = {
            "category": "Категория",
            "title": "Название сбора",
            "short_title": "Короткое название",
            "description": "Полное описание сбора",
            "goal": "Цель сбора",
            "cover_image": "Обложка (фото)",
            "needed_amount": "Нужно собрать (сом)",
            "collected_amount_manual": "Собрано вручную (сом)",
            "safa_amount": "Начисления Safa (сом)",
            "helpers_count_manual": "Помогли вручную (человек)",
            "ends_at": "Дата завершения",
            "status": "Статус сбора",
            "is_featured": "Главный сбор на первом экране",
            "sort_order": "Порядок сортировки",
        }
        help_texts = {
            "category": "Выберите тематическую категорию сбора.",
            "is_featured": "Будет выделен в блоке главного сбора в приложении.",
            "sort_order": "Меньшее число показывается выше в списке.",
        }
        widgets = {
            "ends_at": forms.DateInput(attrs={"type": "date"}),
            "cover_image": forms.FileInput(attrs={"class": "input file-input", "accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "category" in self.fields:
            self.fields["category"].empty_label = "Выберите категорию"
            self.fields["category"].queryset = AmanatCategory.objects.order_by("sort_order", "name")

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.data.get("cover_image-clear") and not self.cleaned_data.get("cover_image"):
            if instance.cover_image:
                instance.cover_image.delete(save=False)
            instance.cover_image = None
        if commit:
            instance.save()
        return instance


class AmanatCategoryForm(StyledModelForm):
    class Meta:
        model = AmanatCategory
        fields = ("name", "slug", "sort_order", "is_active")
        labels = {
            "name": "Название категории",
            "slug": "Код категории (slug)",
            "sort_order": "Порядок сортировки",
            "is_active": "Категория активна",
        }
        help_texts = {
            "name": "Например: Лечение, Малоимущие семьи, Сироты, Образование.",
            "slug": "Уникальный код на латинице (например: medical, orphans, food).",
            "sort_order": "Меньшее число отображается раньше.",
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


class AdminCreateForm(StyledModelForm):
    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Минимум 6 символов"}),
        min_length=6,
        help_text="Минимум 6 символов для входа в панель.",
    )
    password_confirm = forms.CharField(
        label="Подтверждение пароля",
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Повторите пароль"}),
        min_length=6,
    )

    class Meta:
        model = User
        fields = ("phone_number", "first_name", "city", "is_superuser", "is_active")
        labels = {
            "phone_number": "Номер телефона (логин)",
            "first_name": "Имя сотрудника",
            "city": "Город",
            "is_superuser": "Суперпользователь (полный доступ)",
            "is_active": "Доступ активен",
        }
        help_texts = {
            "phone_number": "В формате 996XXXXXXXXX (12 цифр). Будет использоваться для входа.",
            "is_superuser": "Даёт неограниченные административные привилегии.",
        }

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        if phone.startswith("+"):
            phone = phone[1:]
        if not phone.startswith("996"):
            if len(phone) == 9 and phone.startswith(("5", "7", "9", "2", "3")):
                phone = "996" + phone
        return phone

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        password_confirm = cleaned.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "Пароли не совпадают.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        user.is_verify = True
        user.role = User.Roles.CLIENT
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            from apps.users.models import UserProfile

            UserProfile.objects.get_or_create(user=user)
        return user


class AdminEditForm(StyledModelForm):
    new_password = forms.CharField(
        label="Новый пароль (необязательно)",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Оставьте пустым, если не меняется"}),
        min_length=6,
        help_text="Заполняйте только если хотите изменить пароль этого администратора.",
    )
    new_password_confirm = forms.CharField(
        label="Подтверждение нового пароля",
        required=False,
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Повторите новый пароль"}),
        min_length=6,
    )

    class Meta:
        model = User
        fields = ("phone_number", "first_name", "city", "is_superuser", "is_active")
        labels = {
            "phone_number": "Номер телефона (логин)",
            "first_name": "Имя сотрудника",
            "city": "Город",
            "is_superuser": "Суперпользователь (полный доступ)",
            "is_active": "Доступ активен",
        }

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        if phone.startswith("+"):
            phone = phone[1:]
        if not phone.startswith("996"):
            if len(phone) == 9 and phone.startswith(("5", "7", "9", "2", "3")):
                phone = "996" + phone
        return phone

    def clean(self):
        cleaned = super().clean()
        new_password = cleaned.get("new_password")
        new_password_confirm = cleaned.get("new_password_confirm")
        if new_password:
            if new_password != new_password_confirm:
                self.add_error("new_password_confirm", "Новые пароли не совпадают.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        new_password = self.cleaned_data.get("new_password")
        if new_password:
            user.set_password(new_password)
        if commit:
            user.save()
        return user


class AdminPasswordChangeForm(forms.Form):
    old_password = forms.CharField(
        label="Текущий пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Введите текущий пароль", "autofocus": True}),
    )
    new_password = forms.CharField(
        label="Новый пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Минимум 6 символов"}),
        min_length=6,
        help_text="Минимум 6 символов.",
    )
    new_password_confirm = forms.CharField(
        label="Подтвердите новый пароль",
        widget=forms.PasswordInput(attrs={"class": "input", "placeholder": "Повторите новый пароль"}),
        min_length=6,
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data.get("old_password")
        if not self.user.check_password(old_password):
            raise forms.ValidationError("Текущий пароль указан неверно.")
        return old_password

    def clean(self):
        cleaned = super().clean()
        old_password = cleaned.get("old_password")
        new_password = cleaned.get("new_password")
        new_password_confirm = cleaned.get("new_password_confirm")
        if new_password and new_password_confirm:
            if new_password != new_password_confirm:
                self.add_error("new_password_confirm", "Новые пароли не совпадают.")
            elif old_password and old_password == new_password:
                self.add_error("new_password", "Новый пароль должен отличаться от текущего.")
        return cleaned
