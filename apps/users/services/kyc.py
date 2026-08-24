from django.db import transaction
from django.utils import timezone

from apps.users.models import CourierKYC


@transaction.atomic
def set_kyc_status(
    kyc: CourierKYC,
    status: str,
    *,
    comment: str | None = None,
) -> CourierKYC:
    """Apply a KYC decision and keep specialist access in sync."""

    if status not in CourierKYC.Status.values:
        raise ValueError("unsupported_kyc_status")

    locked = CourierKYC.objects.select_for_update().select_related("user").get(
        pk=kyc.pk
    )
    locked.status = status
    locked.checked_at = (
        None if status == CourierKYC.Status.PENDING else timezone.now()
    )
    if comment is not None:
        locked.comment = comment.strip()
    locked.save(update_fields=["status", "checked_at", "comment"])

    user = locked.user
    if status == CourierKYC.Status.APPROVED:
        user.is_active = True
        user.is_verify = True
    else:
        user.is_active = False
    user.save(update_fields=["is_active", "is_verify"])
    if status != CourierKYC.Status.PENDING:
        from apps.notification.events import notify_kyc_status

        transaction.on_commit(lambda: notify_kyc_status(locked))
    return locked
