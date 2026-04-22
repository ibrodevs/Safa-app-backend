import os
import django
from django.conf import settings

# Manual Django setup for sqlite
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# We need to configure settings before django.setup()
# But manage.py already does a lot. 
# Let's try to override the DATABASE setting if it's already configured.

from django.apps import apps
if not apps.ready:
    django.setup()

from apps.users.models import User, CourierKYC, UserProfile
from django.db import transaction

# Override DB to sqlite for this script run if postgres fails
from django import db
try:
    db.connections['default'].ensure_connection()
except Exception:
    print("Postgres connection failed, falling back to sqlite3...")
    settings.DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'db.sqlite3',
    }
    # Reset connection
    del db.connections['default']

phone_number = "996111111111"
password = "password5555"

try:
    with transaction.atomic():
        user, created = User.objects.get_or_create(
            phone_number=phone_number,
            defaults={
                "role": User.Roles.CARRIER,
                "is_verify": True,
                "first_name": "Тачкист",
            }
        )
        if created:
            user.set_password(password)
            user.save()
            print(f"User {phone_number} created.")
        else:
            user.role = User.Roles.CARRIER
            user.is_verify = True
            user.save()
            print(f"User {phone_number} already existed, updated role and verification.")

        kyc, kyc_created = CourierKYC.objects.get_or_create(
            user=user,
            defaults={"status": CourierKYC.Status.APPROVED}
        )
        if not kyc_created:
            kyc.status = CourierKYC.Status.APPROVED
            kyc.save()
            print("KYC updated to approved.")
        else:
            print("KYC created and approved.")

        profile, profile_created = UserProfile.objects.get_or_create(user=user)
        if profile_created:
            print("User profile created.")
        else:
            print("User profile already existed.")

    print(f"Successfully processed user {phone_number}.")
except Exception as e:
    print(f"Error: {e}")
