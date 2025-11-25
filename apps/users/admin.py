from django.contrib import admin
from django import forms
from django.utils import timezone
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, CourierKYC, UserProfile


class UserCreationForm(forms.ModelForm):
    """Форма создания пользователя в админке БЕЗ пароля."""

    class Meta:
        model = User
        fields = (
            "phone_number",
            "first_name",
            "role",
            "is_verify",
            "avatar",
            "is_active",
            "is_staff",
            "is_superuser",
        )

    def save(self, commit=True):
        user = super().save(commit=False)
        # чтобы логин по паролю был невозможен
        user.set_unusable_password()
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """Форма редактирования пользователя в админке, тоже без пароля."""

    class Meta:
        model = User
        fields = (
            "phone_number",
            "first_name",
            "role",
            "is_verify",
            "avatar",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )


class UserProfileInline(admin.StackedInline):
    model = UserProfile
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

    list_display = (
        "id",
        "phone_number",
        "first_name",
        "role",
        "is_verify",
        "is_staff",
        "is_superuser",
        "created_at",
    )
    list_filter = ("role", "is_verify", "is_staff", "is_superuser", "created_at")
    search_fields = ("phone_number", "first_name")
    ordering = ("-created_at",)

    fieldsets = (
        ("Учётные данные", {"fields": ("phone_number",)}),
        ("Личные данные", {"fields": ("first_name", "avatar", "role", "is_verify")}),
        ("Служебное", {"fields": ("last_login", "created_at")}),
    )
    add_fieldsets = (
        (
            "Создание пользователя",
            {
                "classes": ("wide",),
                "fields": (
                    "phone_number",
                    "first_name",
                    "role",
                    "is_verify",
                    "avatar",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )
    readonly_fields = ("last_login", "created_at")

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []

        inline_classes = []
        if obj.role == User.Roles.CLIENT:
            inline_classes = [UserProfileInline]
        elif obj.role == User.Roles.CARRIER:
            inline_classes = [UserProfileInline, CourierKYCInline]

        return [inline_class(self.model, self.admin_site) for inline_class in inline_classes]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from .models import UserProfile, CourierKYC

        if obj.role == User.Roles.CLIENT:
            UserProfile.objects.get_or_create(user=obj)
        elif obj.role == User.Roles.CARRIER:
            UserProfile.objects.get_or_create(user=obj)
            CourierKYC.objects.get_or_create(user=obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related()


@admin.register(CourierKYC)
class CourierKYCAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "checked_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__phone_number", "user__first_name")
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


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "user__first_name", "created_at")
    search_fields = ("user__phone_number", "user__first_name")
    readonly_fields = ("created_at",)
