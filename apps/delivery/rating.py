from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Avg, Count

from apps.users.models import UserProfile

from .models import Shipment, ShipmentReview


def recalculate_carrier_rating(carrier_id: int) -> UserProfile:
    """Synchronize the profile cache with actual 1–5 star reviews."""
    with transaction.atomic():
        profile, _ = UserProfile.objects.get_or_create(user_id=carrier_id)
        profile = UserProfile.objects.select_for_update().get(pk=profile.pk)
        summary = ShipmentReview.objects.filter(
            shipment__carrier_id=carrier_id,
            shipment__status=Shipment.Status.COMPLETED,
        ).aggregate(
            average=Avg("rating"),
            count=Count("id"),
        )
        average = Decimal(str(summary["average"] or 0)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        profile.rate = average
        profile.client_rate_count = int(summary["count"] or 0)
        profile.save(update_fields=["rate", "client_rate_count"])
        return profile
