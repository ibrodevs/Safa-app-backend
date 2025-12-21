from __future__ import annotations
from apps.users.models import User
from django.conf import settings
from django.db import models
from django.utils import timezone

class FCMToken(models.Model):
    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="fcm_tokens",
        verbose_name="Пользователь",
    )
    token = models.CharField(max_length=255, unique=True, verbose_name="FCM токен")
    platform = models.CharField(
        max_length=16,
        choices=Platform.choices,
        default=Platform.ANDROID,
        verbose_name="Платформа",
    )
    device_id = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="ID устройства (опционально)",
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        verbose_name = "FCM токен"
        verbose_name_plural = "FCM токены"

    def __str__(self) -> str:
        return f"{self.user_id}:{self.platform}"


class Notification(models.Model):
    class Channel(models.TextChoices):
        ORDERS = "orders", "Заказы"
        SYSTEM = "system", "Системные"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Пользователь",
    )
    type = models.CharField(
        max_length=64,
        verbose_name="Тип события (shipment_offer/shipment_status/...)",
    )
    channel = models.CharField(
        max_length=32,
        choices=Channel.choices,
        default=Channel.SYSTEM,
        verbose_name="Канал",
    )
    title = models.CharField(max_length=255, blank=True, verbose_name="Заголовок")
    body = models.TextField(blank=True, verbose_name="Текст")
    data = models.JSONField(default=dict, blank=True, verbose_name="Сырые данные")
    event_id = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="event_id из FCM (для дедупа)",
    )
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="Время прочтения")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"

    def __str__(self) -> str:
        return f"{self.user_id}: {self.title or self.type}"





class RoleBroadcast(models.Model):
    APP_CHOICES = (
        ("client", "Клиентское приложение"),
        ("carrier", "Курьерское приложение"),
    )

    ROLE_CHOICES = (
        (User.Roles.CLIENT, "Клиент"),
        (User.Roles.CARRIER, "Курьер"),
    )

    title = models.CharField("Заголовок", max_length=200)
    body = models.TextField("Текст", blank=True)
    app = models.CharField("Приложение", max_length=20, choices=APP_CHOICES)
    role = models.CharField("Роль получателей", max_length=20, choices=ROLE_CHOICES)
    channel = models.CharField("Канал", max_length=50, default="system")
    deep_link = models.CharField("Deep-link", max_length=255, blank=True)
    silent = models.BooleanField("Тихое уведомление", default=False)

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)
    sent_count = models.PositiveIntegerField("Сколько юзеров получили", default=0)

    class Meta:
        verbose_name = "Рассылка по роли"
        verbose_name_plural = "Рассылки по роли"

    def __str__(self) -> str:
        return f"{self.title} → {self.role}"
