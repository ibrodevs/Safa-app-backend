from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, UserProfile, CourierKYC

def _ensure_role_related_records(user: User):
    if user.role == User.Roles.CARRIER:
        UserProfile.objects.get_or_create(user=user)
        CourierKYC.objects.get_or_create(user=user)
    else:
        UserProfile.objects.get_or_create(user=user)
        CourierKYC.objects.filter(user=user).delete()



@receiver(post_save, sender=User)
def create_profiles_on_user_save(sender, instance: User, created: bool, **kwargs):
    transaction.on_commit(lambda: _ensure_role_related_records(instance))
