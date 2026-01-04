from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Tuple

from django.utils import timezone
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from .geo import polyline_len_km, haversine_m

ARRIVAL_RADIUS_M = 50


class Bazar(models.Model):
    name = models.CharField(max_length=155, unique=True, verbose_name="Базар")

    class Meta:
        ordering = ["name"]
        verbose_name = "Базар"
        verbose_name_plural = "Базары"

    def __str__(self) -> str:
        return self.name


class Passage(models.Model):
    bazar = models.ForeignKey(Bazar, on_delete=models.PROTECT, related_name="passages", verbose_name="Базар")
    number = models.CharField(max_length=50, verbose_name="Проход")

    class Meta:
        ordering = ["bazar__name", "number"]
        verbose_name = "Проход"
        verbose_name_plural = "Проходы"
        constraints = [
            models.UniqueConstraint(fields=["bazar", "number"], name="uniq_passage_bazar_number"),
        ]

    def __str__(self) -> str:
        return f"{self.number} проход — {self.bazar.name}"


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

    @property
    def bazar(self) -> Bazar:
        return self.passage.bazar

    @property
    def ui_label(self) -> str:
        return f"Контейнер {self.number}, {self.passage.number} проход"

    @property
    def display_title(self) -> str:
        base = self.title.strip() if self.title else ""
        if base:
            return f"{base} · {self.ui_label} · {self.bazar.name}"
        return f"{self.ui_label} · {self.bazar.name}"

    def __str__(self) -> str:
        return self.display_title


class CourierSegment(models.Model):
    name = models.CharField(max_length=64, unique=True, verbose_name="Название")
    slug = models.SlugField(max_length=32, unique=True, verbose_name="Код")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок в UI")
    icon = models.ImageField(null=True, blank=True, verbose_name="Иконка")

    base_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Базовая цена",
    )
    per_km_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name="Цена за км",
    )
    min_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Минималка")
    description = models.TextField(verbose_name=("Описание"), null=True, blank=True)

    fragile_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Наценка за хрупкость, %",
    )
    size_s_multiplier = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("1.00"), verbose_name="Множитель для S (мал.)"
    )
    size_m_multiplier = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("1.00"), verbose_name="Множитель для M (сред.)"
    )
    size_l_multiplier = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("1.15"), verbose_name="Множитель для L (больш.)"
    )

    per_unit = models.BooleanField(default=True, verbose_name="Цена за единицу")

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Сегмент тарифа"
        verbose_name_plural = "Сегменты тарифа"

    def __str__(self) -> str:
        return self.name


class Shipment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "В ожидании"
        ASSIGNED = "assigned", "Назначен"
        IN_TRANSIT = "in_transit", "В пути"
        COMPLETED = "completed", "Завершено"
        CANCELED = "canceled", "Отменено"

    class Size(models.TextChoices):
        S = "S", "Маленькая"
        M = "M", "Средняя"
        L = "L", "Большая"

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
    segment = models.ForeignKey(CourierSegment, on_delete=models.PROTECT, related_name="shipments", verbose_name="Тариф")

    size = models.CharField(max_length=1, choices=Size.choices, default=Size.M, verbose_name="Размер")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Кол-во")
    fragile = models.BooleanField(default=False, verbose_name="Хрупкая")
    description = models.CharField(max_length=255, blank=True, verbose_name="Описание")

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

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Посылка"
        verbose_name_plural = "Посылки"

    def __str__(self) -> str:
        return f"Посылка №{self.id} {self.title}"

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

    def _size_multiplier(self) -> Decimal:
        if self.size == self.Size.S:
            return Decimal(self.segment.size_s_multiplier or 1)
        if self.size == self.Size.L:
            return Decimal(self.segment.size_l_multiplier or 1)
        return Decimal(self.segment.size_m_multiplier or 1)

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
        base = Decimal(self.segment.base_price) + Decimal(self.segment.per_km_price) * Decimal(self.distance_km)
        mult = self._size_multiplier()
        if self.fragile:
            mult *= (Decimal("1") + Decimal(self.segment.fragile_pct or 0) / Decimal("100"))
        cost = base * mult
        if self.segment.per_unit:
            cost *= Decimal(self.quantity or 1)
        cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cost = max(cost, Decimal(self.segment.min_fare or 0))
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
