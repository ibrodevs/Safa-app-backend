from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, ClientProfile, CarrierProfile, CourierKYC

def _ensure_role_related_records(user: User):
    if user.role == User.Roles.CARRIER:
        CarrierProfile.objects.get_or_create(user=user)
        CourierKYC.objects.get_or_create(user=user)
        ClientProfile.objects.filter(user=user).delete()
    else:
        ClientProfile.objects.get_or_create(user=user)
        CarrierProfile.objects.filter(user=user).delete()
        CourierKYC.objects.filter(user=user).delete()

@receiver(post_save, sender=User)
def create_profiles_on_user_save(sender, instance: User, created: bool, **kwargs):
    transaction.on_commit(lambda: _ensure_role_related_records(instance))
