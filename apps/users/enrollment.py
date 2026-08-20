from __future__ import annotations

from django.conf import settings
from django.core import signing

from .models import User


KYC_ENROLLMENT_SALT = "safa.kyc.enrollment.v1"


class InvalidKYCEnrollmentToken(ValueError):
    pass


def make_kyc_enrollment_token(user: User) -> str:
    return signing.dumps(
        {"user_id": user.pk, "phone": user.phone_number},
        salt=KYC_ENROLLMENT_SALT,
        compress=True,
    )


def user_from_kyc_enrollment_token(token: str) -> User:
    max_age = int(getattr(settings, "KYC_ENROLLMENT_TOKEN_MAX_AGE", 60 * 60 * 24 * 30))
    try:
        payload = signing.loads(
            str(token or ""),
            salt=KYC_ENROLLMENT_SALT,
            max_age=max_age,
        )
        user = User.objects.get(
            pk=payload.get("user_id"),
            phone_number=payload.get("phone"),
            role=User.Roles.CARRIER,
        )
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist, TypeError):
        raise InvalidKYCEnrollmentToken("invalid_kyc_token")
    return user
