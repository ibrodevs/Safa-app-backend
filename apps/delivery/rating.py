from decimal import Decimal
from django.db import transaction
from apps.users.models import UserProfile, User
from .models import Shipment


def apply_rating_for_completed_shipment(shipment: Shipment) -> None:
    if not shipment.carrier_id:
        return
    if shipment.status != Shipment.Status.COMPLETED:
        return

    with transaction.atomic():
        s = (
            Shipment.objects
            .select_for_update()
            .get(pk=shipment.pk)
        )
        if s.rating_applied or not s.carrier_id or s.status != Shipment.Status.COMPLETED:
            return

        profile, _ = UserProfile.objects.get_or_create(user_id=s.carrier_id)

        current_rate = profile.rate or 0
        current_clients = profile.client_rate_count or 0

        new_rate = min(100, current_rate + 1)
        profile.rate = new_rate
        profile.client_rate_count = current_clients + 1
        profile.save(update_fields=["rate", "client_rate_count"])

        s.rating_applied = True
        s.save(update_fields=["rating_applied"])
