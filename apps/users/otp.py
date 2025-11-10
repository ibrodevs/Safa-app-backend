import secrets
from django.conf import settings
from apps.users.utlis import normalize_phone, is_static_otp_phone, static_otp_for

def generate_otp(length: int | None = None, phone: str | None = None) -> str:
    if phone:
        phone = normalize_phone(phone)
        if is_static_otp_phone(phone):
            return static_otp_for(phone) or "1111"
    length = length or int(getattr(settings, "OTP_LENGTH", 4))
    return "".join(str(secrets.randbelow(10)) for _ in range(length))
