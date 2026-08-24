import json

from django import template
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html

register = template.Library()


@register.filter
def money(value):
    try:
        amount = int(value or 0)
    except (TypeError, ValueError):
        amount = 0
    return f"{amount:,}".replace(",", " ") + " сом"


@register.filter
def phone(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if len(digits) == 12 and digits.startswith("996"):
        return f"+996 {digits[3:6]} {digits[6:9]} {digits[9:12]}"
    return str(value or "—")


@register.filter
def panel_datetime(value):
    if not value:
        return "—"
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    return date_format(local, "j M Y, H:i", use_l10n=True)


@register.filter
def json_pretty(value):
    return json.dumps(value or {}, ensure_ascii=False, indent=2, sort_keys=True)


@register.simple_tag
def status_badge(code, label=None):
    raw_code = str(code or "")
    normalized = raw_code.lower()
    tone = {
        "pending": "warning",
        "assigned": "info",
        "in_transit": "violet",
        "awaiting_payment": "warning",
        "completed": "success",
        "canceled": "danger",
        "approved": "success",
        "rejected": "danger",
        "active": "success",
        "draft": "neutral",
        "published": "success",
        "archived": "neutral",
        "succeeded": "success",
        "failed": "danger",
        "paid": "success",
        "credited": "success",
    }.get(normalized, "neutral")
    payment_labels = {"PENDING": "Ожидает", "SUCCEEDED": "Оплачено", "FAILED": "Ошибка"}
    text = payment_labels.get(raw_code, label or code or "—")
    return format_html(
        '<span class="badge badge--{}"><span class="badge__dot"></span>{}</span>',
        tone,
        text,
    )
