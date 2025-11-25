from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Tuple

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from .geo import polyline_len_km, haversine_m

ARRIVAL_RADIUS_M = 50


class CourierSegment(models.Model):
    name = models.CharField(max_length=64, unique=True, verbose_name="Название")
    slug = models.SlugField(max_length=32, unique=True, verbose_name="Код")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    order = models.PositiveSmallIntegerField(default=0, verbose_name="Порядок в UI")
    icon = models.CharField(max_length=64, blank=True, verbose_name="Иконка")

    base_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], verbose_name="Посадка")
    per_km_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], verbose_name="Цена за км")
    min_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Минималка")

    fragile_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"), verbose_name="Хрупкость, %")
    size_s_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"), verbose_name="×S")
    size_m_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"), verbose_name="×M")
    size_l_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.15"), verbose_name="×L")

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

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="Статус")
    current_stop_index = models.PositiveSmallIntegerField(default=1, verbose_name="Индекс цели")
    eta_to_next_min = models.DecimalField(max_digits=6, decimal_places=1, default=0, verbose_name="ETA, мин")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

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
        return [(s.lat, s.lon) for s in qs]

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
        if not nxt:
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
        return self.final_fare


class ShipmentStop(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="stops", verbose_name="Посылка")
    title = models.CharField(max_length=255, verbose_name="Адрес / подпись")
    lat = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Широта (lat)")
    lon = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Долгота (lon)")
    position = models.PositiveSmallIntegerField(verbose_name="Позиция", null=True, blank=True)

    class Meta:
        unique_together = [("shipment", "position")]
        ordering = ["position"]
        verbose_name = "Остановка"
        verbose_name_plural = "Остановки"

    def __str__(self) -> str:
        return f"{self.shipment_id}:{self.position}"


class CourierPosition(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="position", verbose_name="Пользователь")
    lat = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Широта (lat)")
    lon = models.DecimalField(max_digits=9, decimal_places=6, verbose_name="Долгота (lon)")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")

    class Meta:
        verbose_name = "Позиция курьера"
        verbose_name_plural = "Позиции курьеров"

    def __str__(self) -> str:
        return f"{self.user_id}@{self.lat},{self.lon}"
