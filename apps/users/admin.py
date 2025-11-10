# users/admin.py
from django.contrib import admin
from django import forms
from django.utils import timezone
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField

from .models import User, CourierKYC, ClientProfile, CarrierProfile



class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="Пароль", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Подтверждение пароля", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("phone_number", "first_name", "last_name", "email", "role", "is_verify", "avatar",
                  "is_staff", "is_superuser", "is_active")

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Пароли не совпадают.")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    password = ReadOnlyPasswordHashField(label="Пароль",
        help_text="Чтобы сменить пароль, используйте кнопку «Изменить пароль» на странице пользователя.")

    class Meta:
        model = User
        fields = ("phone_number", "password", "first_name", "last_name", "email", "role", "is_verify",
                  "avatar", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")

    def clean_password(self):
        return self.initial.get("password")


class ClientProfileInline(admin.StackedInline):
    model = ClientProfile
    can_delete = False
    extra = 0
    fk_name = "user"
    show_change_link = True


class CarrierProfileInline(admin.StackedInline):
    model = CarrierProfile
    can_delete = False
    extra = 0
    fk_name = "user"
    show_change_link = True


class CourierKYCInline(admin.StackedInline):
    model = CourierKYC
    can_delete = False
    extra = 0
    fk_name = "user"
    show_change_link = True



@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    list_display = ("id", "phone_number", "first_name", "last_name", "role",
                    "is_verify", "is_staff", "is_superuser", "created_at")
    list_filter = ("role", "is_verify", "is_staff", "is_superuser", "created_at")
    search_fields = ("phone_number", "first_name", "last_name", "email")
    ordering = ("-created_at",)

    fieldsets = (
        ("Учётные данные", {"fields": ("phone_number", "password")}),
        ("Личные данные", {"fields": ("first_name", "last_name", "email", "avatar", "role", "is_verify")}),
        ("Служебное", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        ("Создание пользователя", {
            "classes": ("wide",),
            "fields": ("phone_number", "first_name", "last_name", "email", "role", "is_verify", "avatar",
                       "is_active", "is_staff", "is_superuser", "password1", "password2"),
        }),
    )
    readonly_fields = ("last_login", "created_at")
    
    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []

        inline_classes = []
        if obj.role == User.Roles.CLIENT:
            inline_classes = [ClientProfileInline]
        elif obj.role == User.Roles.CARRIER:
            inline_classes = [CarrierProfileInline, CourierKYCInline]

        return [inline_class(self.model, self.admin_site) for inline_class in inline_classes]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from .models import ClientProfile, CarrierProfile, CourierKYC
        if obj.role == User.Roles.CLIENT:
            ClientProfile.objects.get_or_create(user=obj)
        elif obj.role == User.Roles.CARRIER:
            CarrierProfile.objects.get_or_create(user=obj)
            CourierKYC.objects.get_or_create(user=obj)



    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related()



@admin.register(CourierKYC)
class CourierKYCAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "checked_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__phone_number", "user__first_name", "user__last_name", "user__email")
    readonly_fields = ("created_at",)

    actions = ["mark_approved", "mark_rejected", "mark_pending"]

    @admin.action(description="Одобрить KYC")
    def mark_approved(self, request, queryset):
        updated = queryset.update(status=CourierKYC.Status.APPROVED, checked_at=timezone.now())
        self.message_user(request, f"Одобрено: {updated}")

    @admin.action(description="Отклонить KYC")
    def mark_rejected(self, request, queryset):
        updated = queryset.update(status=CourierKYC.Status.REJECTED, checked_at=timezone.now())
        self.message_user(request, f"Отклонено: {updated}")

    @admin.action(description="Вернуть на проверку")
    def mark_pending(self, request, queryset):
        updated = queryset.update(status=CourierKYC.Status.PENDING, checked_at=None)
        self.message_user(request, f"На проверке: {updated}")



@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "user__first_name","created_at")
    search_fields = ("user__phone_number", "user__first_name", "user__last_name", "user__email")
    readonly_fields = ("created_at",)


@admin.register(CarrierProfile)
class CarrierProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "user__first_name","created_at")
    search_fields = ("user__phone_number", "user__first_name", "user__last_name", "user__email")
    readonly_fields = ("created_at",)


