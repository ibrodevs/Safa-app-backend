from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Tuple

from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .geo import polyline_len_km, haversine_m

ARRIVAL_RADIUS_M = 50


class DeliveryDistrict(models.Model):
    name = models.CharField(max_length=155, unique=True, verbose_name="Район")
    fixed_price = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Фиксированная цена внутри района",
    )
    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Базовая стоимость района",
    )
    per_km_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Стоимость за км в районе",
    )
    min_fare = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Минималка района",
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        ordering = ["name"]
        verbose_name = "Тариф района"
        verbose_name_plural = "Тарифы районов"

    def __str__(self) -> str:
        return self.name


class Bazar(models.Model):
    name = models.CharField(max_length=155, unique=True, verbose_name="Базар")
    district = models.CharField(max_length=155, blank=True, verbose_name="Район")
    district_tariff = models.ForeignKey(
        DeliveryDistrict,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bazars",
        verbose_name="Тариф района",
    )
    fixed_price = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Фиксированная цена базара",
    )
    price_from = models.PositiveIntegerField(null=True, blank=True, verbose_name="Цена от")
    price_to = models.PositiveIntegerField(null=True, blank=True, verbose_name="Цена до")
    top_left_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="Широта (верх-лево)")
    top_left_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="Долгота (верх-лево)")
    bottom_right_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="Широта (низ-право)")
    bottom_right_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, verbose_name="Долгота (низ-право)")

    class Meta:
        ordering = ["name"]
        verbose_name = "Базар"
        verbose_name_plural = "Базары"

    def __str__(self) -> str:
        return self.name

    @property
    def effective_fixed_price(self) -> int | None:
        if self.fixed_price is not None:
            return int(self.fixed_price)
        if self.price_from is not None:
            return int(self.price_from)
        if self.district_tariff and self.district_tariff.fixed_price is not None:
            return int(self.district_tariff.fixed_price)
        return None


class Passage(models.Model):
    bazar = models.ForeignKey(Bazar, on_delete=models.PROTECT, related_name="passages", verbose_name="Базар")

    # Район, внутри которого лежит проход на карте (пусто — проход вне районов).
    # Номера проходов уникальны в пределах района, а не всего базара: в разных
    # районах одного базара спокойно бывают «1 проход», «2 проход» и т.д.
    district = models.CharField(max_length=155, blank=True, verbose_name="Район")
    number = models.CharField(max_length=50, verbose_name="Проход")

    # Наклон линии прохода на карте: 0° — на восток, отсчёт по часовой стрелке,
    # диапазон 0–180° (направление рисования не важно). Под этим же углом удобно
    # ставить и дублировать контейнеры вдоль прохода.
    angle = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name="Угол наклона, °",
    )

    class Meta:
        ordering = ["bazar__name", "district", "number"]
        verbose_name = "Проход"
        verbose_name_plural = "Проходы"
        constraints = [
            models.UniqueConstraint(
                fields=["bazar", "district", "number"],
                name="uniq_passage_bazar_district_number",
            ),
        ]

    @property
    def angle_label(self) -> str:
        return f"{self.angle:g}°" if self.angle is not None else "—"

    @property
    def ui_label(self) -> str:
        if self.district:
            return f"{self.number} проход · {self.district}"
        return f"{self.number} проход"

    def __str__(self) -> str:
        return f"{self.ui_label} — {self.bazar.name}"


class Container(models.Model):
    passage = models.ForeignKey(Passage, on_delete=models.PROTECT, related_name="containers", verbose_name="Проход")
    number = models.CharField(max_length=50, verbose_name="Номер")
    title = models.CharField(max_length=150, blank=True, verbose_name="Название")

    lat = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Широта (lat)")
    lon = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Долгота (lon)")

    is_active = models.BooleanField(default=True, verbose_name="Активен")

    class Meta:
        ordering = ["passage__bazar__name", "passage__number", "number"]
        verbose_name = "Контейнер"
        verbose_name_plural = "Контейнеры"
        constraints = [
            models.UniqueConstraint(fields=["passage", "number"], name="uniq_container_passage_number"),
        ]
        indexes = [
            models.Index(
                fields=("is_active", "lat", "lon"),
                name="container_viewport_idx",
            ),
        ]

    @property
    def bazar(self) -> Bazar:
        return self.passage.bazar

    @property
    def ui_label(self) -> str:
        # Проход подписывается вместе со своим районом: в разных районах базара
        # номера проходов повторяются, и без района адрес неоднозначен.
        return f"Контейнер {self.number}, {self.passage.ui_label}"

    @property
    def display_title(self) -> str:
        base = self.title.strip() if self.title else ""
        if base:
            return f"{base} · {self.ui_label} · {self.bazar.name}"
        return f"{self.ui_label} · {self.bazar.name}"

    def __str__(self) -> str:
        return self.display_title


class AmanatCategory(models.Model):
    name = models.CharField(max_length=80, unique=True, verbose_name="Категория")
    slug = models.SlugField(max_length=90, unique=True, verbose_name="Slug")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")
    is_active = models.BooleanField(default=True, verbose_name="Активна")

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "Аманат категория"
        verbose_name_plural = "Аманат категории"

    def __str__(self) -> str:
        return self.name


class AmanatCampaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ACTIVE = "active", "Активен"
        COMPLETED = "completed", "Завершён"
        CANCELED = "canceled", "Отменён"

    category = models.ForeignKey(
        AmanatCategory,
        on_delete=models.PROTECT,
        related_name="campaigns",
        verbose_name="Категория",
    )
    title = models.CharField(max_length=180, verbose_name="Название")
    short_title = models.CharField(max_length=180, blank=True, verbose_name="Короткое название")
    description = models.TextField(verbose_name="Описание")
    goal = models.CharField(max_length=255, blank=True, verbose_name="Цель")
    needed_amount = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="Нужно собрать")
    collected_amount_manual = models.PositiveIntegerField(default=0, verbose_name="Собрано вручную")
    safa_amount = models.PositiveIntegerField(default=0, verbose_name="Начисления Safa")
    helpers_count_manual = models.PositiveIntegerField(default=0, verbose_name="Помогли вручную")
    cover_image = models.ImageField(upload_to="amanat/campaigns/", null=True, blank=True, verbose_name="Фото")
    ends_at = models.DateField(null=True, blank=True, verbose_name="Дата завершения")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, verbose_name="Статус")
    is_featured = models.BooleanField(default=False, verbose_name="Главный сбор")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменён")

    class Meta:
        ordering = ("sort_order", "-created_at")
        verbose_name = "Аманат сбор"
        verbose_name_plural = "Аманат сборы"

    def __str__(self) -> str:
        return self.title

    @property
    def paid_donations_amount(self) -> int:
        annotated = getattr(self, "_paid_donations_amount", None)
        if annotated is not None:
            return int(annotated)
        value = self.donations.filter(status=AmanatDonation.Status.PAID).aggregate(
            total=models.Sum("amount")
        )["total"]
        return int(value or 0)

    @property
    def voluntary_amount(self) -> int:
        return int(self.collected_amount_manual or 0) + self.paid_donations_amount

    @property
    def collected_amount(self) -> int:
        return self.voluntary_amount + int(self.safa_amount or 0)

    @property
    def remaining_amount(self) -> int:
        return max(int(self.needed_amount or 0) - self.collected_amount, 0)

    @property
    def helpers_count(self) -> int:
        annotated = getattr(self, "_paid_donations_count", None)
        if annotated is not None:
            return int(self.helpers_count_manual or 0) + int(annotated)
        paid_count = self.donations.filter(status=AmanatDonation.Status.PAID).count()
        return int(self.helpers_count_manual or 0) + paid_count


class AmanatDonation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "В ожидании"
        PAID = "paid", "Оплачено"
        FAILED = "failed", "Ошибка"
        CANCELED = "canceled", "Отменено"

    campaign = models.ForeignKey(
        AmanatCampaign,
        on_delete=models.CASCADE,
        related_name="donations",
        verbose_name="Сбор",
    )
    donor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="amanat_donations",
        verbose_name="Пользователь",
    )
    donor_label = models.CharField(max_length=120, blank=True, verbose_name="Имя/телефон для отображения")
    amount = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="Сумма")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Статус")
    is_anonymous = models.BooleanField(default=False, verbose_name="Анонимно")
    comment = models.CharField(max_length=255, blank=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачено в")

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Аманат пожертвование"
        verbose_name_plural = "Аманат пожертвования"

    def save(self, *args, **kwargs):
        if self.status == self.Status.PAID and self.paid_at is None:
            self.paid_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.campaign} · {self.amount} сом"


class AmanatDocument(models.Model):
    campaign = models.ForeignKey(
        AmanatCampaign,
        on_delete=models.CASCADE,
        related_name="documents",
        verbose_name="Сбор",
    )
    title = models.CharField(max_length=200, verbose_name="Название документа")
    file = models.FileField(
        upload_to="amanat/documents/",
        verbose_name="Файл документа (PDF, изображение, скан)",
    )
    description = models.TextField(blank=True, verbose_name="Описание / примечание")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата добавления")

    class Meta:
        ordering = ("sort_order", "-created_at")
        verbose_name = "Отчётный документ"
        verbose_name_plural = "Отчётные документы"

    def __str__(self) -> str:
        return f"{self.campaign} · {self.title}"


class GlobalDeliveryConfig(models.Model):
    """Глобальные настройки доставки (Одиночка)"""
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=50, verbose_name="Базовая стоимость")
    per_km_price = models.DecimalField(max_digits=10, decimal_places=2, default=20, verbose_name="Стоимость за км")
    min_fare = models.DecimalField(max_digits=10, decimal_places=2, default=50, verbose_name="Минималка")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Изменено")

    class Meta:
        verbose_name = "Глобальные настройки цен"
        verbose_name_plural = "Глобальные настройки цен"

    def __str__(self) -> str:
        return "Настройки цен"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls) -> "GlobalDeliveryConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Shipment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "В ожидании"
        ASSIGNED = "assigned", "Назначен"
        IN_TRANSIT = "in_transit", "В пути"
        AWAITING_PAYMENT = "awaiting_payment", "Ожидает оплаты"
        COMPLETED = "completed", "Завершено"
        CANCELED = "canceled", "Отменено"

    class ServiceType(models.TextChoices):
        AMANAT = "amanat", "Аманат"
        CARS = "cars", "Тачки"
        DELIVERY = "delivery", "Доставка"

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="shipments_as_client",
        verbose_name="Клиент",
    )
    carrier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shipments_as_carrier",
        verbose_name="Курьер",
    )

    title = models.CharField(max_length=155, verbose_name="Название посылки")
    service_type = models.CharField(
        max_length=20,
        choices=ServiceType.choices,
        default=ServiceType.DELIVERY,
        verbose_name="Тип услуги",
    )

    description = models.CharField(max_length=255, blank=True, verbose_name="Описание")
    is_demo = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Демонстрационный заказ",
    )

    distance_km = models.DecimalField(max_digits=7, decimal_places=2, default=0, verbose_name="Дистанция, км")
    estimated_fare = models.PositiveIntegerField(default=0, verbose_name="Предварительная стоимость")
    final_fare = models.PositiveIntegerField(default=0, verbose_name="Итоговая стоимость")
    rating_applied = models.BooleanField(default=False, verbose_name="Рейтинг начислен")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Статус")
    is_paid = models.BooleanField(default=False, verbose_name="Оплачено")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Оплачено в")
    current_stop_index = models.PositiveSmallIntegerField(default=1, verbose_name="Индекс цели")
    eta_to_next_min = models.DecimalField(max_digits=6, decimal_places=1, default=0, verbose_name="ETA, мин")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name="Завершено")
    work_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Работа выполнена специалистом",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Посылка"
        verbose_name_plural = "Посылки"
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(status="completed")
                    | models.Q(is_paid=True)
                ),
                name="delivery_completed_requires_payment",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "carrier", "is_demo", "created_at"),
                name="shipment_nearby_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Посылка №{self.id} {self.title}"

    def clean(self):
        super().clean()
        if self.status == self.Status.COMPLETED and not self.is_paid:
            raise ValidationError(
                {
                    "status": (
                        "Нельзя завершить неоплаченный заказ. "
                        "Отметьте «Оплачено» в разделе оплаты или выберите "
                        "статус «Ожидает оплаты»."
                    )
                }
            )

    @property
    def public_code(self) -> str:
        return f"{self.id:04d}"

    def _route_points(self) -> List[Tuple[float, float]]:
        qs = self.stops.order_by("position")
        pts: List[Tuple[float, float]] = []
        for s in qs:
            if s.lat is None or s.lon is None:
                # Маршрут не заполнен полностью (например, в админке ещё не выбрали контейнер).
                return []
            pts.append((float(s.lat), float(s.lon)))
        return pts

    def route_distance_km(self) -> Decimal:
        km = Decimal(str(polyline_len_km(self._route_points())))
        return km.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def next_stop(self) -> Optional["ShipmentStop"]:
        stops = list(self.stops.order_by("position"))
        if self.current_stop_index >= len(stops):
            return None
        return stops[self.current_stop_index]

    def distance_to_next_m(self, lat: float, lon: float) -> Decimal:
        nxt = self.next_stop()
        if not nxt or nxt.lat is None or nxt.lon is None:
            return Decimal("0")
        d = haversine_m(lat, lon, float(nxt.lat), float(nxt.lon))
        return Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def estimate(self) -> int:
        self.distance_km = self.route_distance_km()

        fixed_prices: list[int] = []
        bazaars_with_coords = None
        all_stops_in_bazar = True

        for stop in self.stops.all():
            stop_matched = False

            if stop.container_id:
                bazar = stop.container.passage.bazar
                price = bazar.effective_fixed_price
                if price is not None:
                    fixed_prices.append(price)
                    stop_matched = True

            if not stop_matched and stop.lat is not None and stop.lon is not None:
                if bazaars_with_coords is None:
                    bazaars_with_coords = Bazar.objects.select_related(
                        "district_tariff",
                    ).filter(
                        top_left_lat__isnull=False,
                        top_left_lon__isnull=False,
                        bottom_right_lat__isnull=False,
                        bottom_right_lon__isnull=False,
                    )

                # Проверка вхождения координаты в прямоугольник базара
                for bazar in bazaars_with_coords:
                    if (bazar.bottom_right_lat <= stop.lat <= bazar.top_left_lat) and \
                       (bazar.top_left_lon <= stop.lon <= bazar.bottom_right_lon):
                        price = bazar.effective_fixed_price
                        if price is not None:
                            fixed_prices.append(price)
                            stop_matched = True
                        break

            if not stop_matched:
                all_stops_in_bazar = False

        # Если все точки маршрута внутри базаров, берём максимальный
        # фиксированный тариф базара/района среди точек.
        if all_stops_in_bazar and fixed_prices:
            self.estimated_fare = max(fixed_prices)
            return self.estimated_fare
        
        # Иначе кто-то за пределами базара — считаем по километражу.
        config = GlobalDeliveryConfig.get_config()
        base_price = Decimal(config.base_price)
        per_km_price = Decimal(config.per_km_price)
        min_fare = Decimal(config.min_fare)

        cost = base_price + per_km_price * Decimal(self.distance_km)
        cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        if cost < min_fare:
            cost = min_fare

        self.estimated_fare = int(cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return self.estimated_fare

    def finalize(self) -> int:
        self.final_fare = self.estimated_fare
        if not self.finished_at:
            self.finished_at = timezone.now()
        return self.final_fare

    @property
    def commission_amount(self) -> int:
        pct = getattr(settings, "PLATFORM_COMMISSION_PCT", Decimal("0"))
        fare = Decimal(self.final_fare or self.estimated_fare or 0)
        value = (fare * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(value)

    @property
    def courier_income(self) -> int:
        fare = int(self.final_fare or self.estimated_fare or 0)
        return fare - self.commission_amount


class ShipmentStop(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="stops", verbose_name="Посылка")

    # Если указали контейнер — координаты будут взяты из него (и можно не заполнять lat/lon руками).
    container = models.ForeignKey(
        Container,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shipment_stops",
        verbose_name="Контейнер",
    )

    title = models.CharField(max_length=255, verbose_name="Адрес / подпись", null=True, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Широта (lat)", null=True, blank=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Долгота (lon)", null=True, blank=True)

    position = models.PositiveSmallIntegerField(verbose_name="Позиция", null=True, blank=True)

    class Meta:
        unique_together = [("shipment", "position")]
        ordering = ["position"]
        verbose_name = "Остановка"
        verbose_name_plural = "Остановки"

    def __str__(self) -> str:
        return f"{self.shipment_id}:{self.position}"

    def apply_container(self) -> None:
        if not self.container_id:
            return
        c = self.container
        # Координаты всегда из контейнера (они - источник истины).
        self.lat = c.lat
        self.lon = c.lon
        # title можно кастомизировать; если пусто — заполним автоматически.
        if not (self.title or "").strip():
            self.title = c.display_title

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.container_id:
            # Если update_fields ограничены (например, меняем только position),
            # то не трогаем остальные поля, чтобы не было сюрпризов.
            if not update_fields or any(f in update_fields for f in ("title", "lat", "lon", "container")):
                self.apply_container()
        super().save(*args, **kwargs)


class CourierPosition(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="position",
        verbose_name="Пользователь",
    )
    lat = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Широта (lat)")
    lon = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Долгота (lon)")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Позиция курьера"
        verbose_name_plural = "Позиции курьеров"

    def __str__(self) -> str:
        return f"{self.user_id}@{self.lat},{self.lon}"


class SupportContact(models.Model):
    phone = models.CharField(
        max_length=50,
        default="+996 509 10 67 88",
        verbose_name="Телефон поддержки",
    )
    telegram = models.CharField(
        max_length=100,
        default="996509106788",
        verbose_name="Telegram (username или телефон)",
    )
    whatsapp = models.CharField(
        max_length=50,
        default="+996509106788",
        blank=True,
        verbose_name="WhatsApp",
    )
    working_hours = models.CharField(
        max_length=255,
        default="Ежедневно с 09:00 до 21:00 по Бишкеку.",
        verbose_name="Часы работы",
    )
    message = models.TextField(
        default="Если что-то пошло не так — напишите нам или позвоните. Мы поможем с заказами, оплатой и приложением.",
        verbose_name="Текст сообщения",
    )
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Служба поддержки"
        verbose_name_plural = "Служба поддержки"

    def __str__(self) -> str:
        return f"Служба поддержки ({self.phone})"

    @classmethod
    def get_solo(cls) -> SupportContact:
        obj, _ = cls.objects.get_or_create(
            id=1,
            defaults={
                "phone": "+996 509 10 67 88",
                "telegram": "996509106788",
                "whatsapp": "+996509106788",
                "working_hours": "Ежедневно с 09:00 до 21:00 по Бишкеку.",
                "message": "Если что-то пошло не так — напишите нам или позвоните. Мы поможем с заказами, оплатой и приложением.",
                "is_active": True,
            },
        )
        return obj


class PrivacyPolicy(models.Model):
    content = models.TextField(
        verbose_name="Текст политики конфиденциальности",
        default=(
            "1. Какие данные мы собираем\n"
            "Мы собираем данные, необходимые для работы сервиса доставки: ваше имя, номер телефона, "
            "данные о местоположении для отслеживания посылок в реальном времени, а также информацию о ваших заказах.\n\n"
            "2. Как мы используем данные\n"
            "Ваше местоположение используется для построения маршрута курьером и информирования клиента о статусе доставки. "
            "Номер телефона необходим для связи и подтверждения заказов.\n\n"
            "3. Передача данных третьим лицам\n"
            "Мы не продаём ваши данные. Данные передаются только участникам процесса доставки "
            "(курьеру или клиенту) исключительно для выполнения услуги.\n\n"
            "4. Безопасность\n"
            "Мы используем современные методы шифрования для защиты вашей личной информации и данных о платежах.\n\n"
            "5. Ваши права\n"
            "Вы имеете право запросить удаление вашего аккаунта и всех связанных данных в любой момент через службу поддержки."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Политика конфиденциальности"
        verbose_name_plural = "Политика конфиденциальности"

    def __str__(self) -> str:
        return f"Политика конфиденциальности (обновлено {self.updated_at.strftime('%d.%m.%Y %H:%M') if self.updated_at else ''})"

    @classmethod
    def get_solo(cls) -> PrivacyPolicy:
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class FAQItem(models.Model):
    question = models.CharField(max_length=255, verbose_name="Вопрос")
    answer = models.TextField(verbose_name="Ответ")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлен")

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "Частый вопрос (FAQ)"
        verbose_name_plural = "Частые вопросы (FAQ)"

    def __str__(self) -> str:
        return self.question

