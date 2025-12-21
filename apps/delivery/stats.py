from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum, Count
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.conf import settings

from .models import Shipment


def carrier_daily_stats(*, carrier_id: int, day: date) -> dict:
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end = start + timedelta(days=1)

    qs = Shipment.objects.filter(
        carrier_id=carrier_id,
        status=Shipment.Status.COMPLETED,
        finished_at__gte=start,
        finished_at__lt=end,
    )

    agg = qs.aggregate(
        gross_total=Coalesce(Sum("final_fare"), 0),
        clients_count=Count("client", distinct=True),
    )

    gross = Decimal(agg["gross_total"] or 0)
    clients = int(agg["clients_count"] or 0)

    pct = getattr(settings, "PLATFORM_COMMISSION_PCT", Decimal("0"))
    commission = (gross * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    earned = gross - commission

    return {
        "date": day.isoformat(),
        "gross_total": int(gross),       # общий оборот
        "earned": int(earned),           # чистый доход курьера
        "commission": int(commission),   # комиссия платформы
        "clients": clients,              # уникальных клиентов
    }


def carrier_daily_stats_with_change(*, carrier_id: int, day: date) -> dict:
    today_stats = carrier_daily_stats(carrier_id=carrier_id, day=day)
    prev_day = day - timedelta(days=1)
    prev_stats = carrier_daily_stats(carrier_id=carrier_id, day=prev_day)

    prev_earned = Decimal(prev_stats["earned"] or 0)
    curr_earned = Decimal(today_stats["earned"] or 0)

    if prev_earned <= 0:
        change_pct = None
    else:
        diff = ((curr_earned - prev_earned) / prev_earned) * Decimal("100")
        change_pct = int(diff.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    today_stats["change_percent_vs_prev"] = change_pct
    return today_stats
