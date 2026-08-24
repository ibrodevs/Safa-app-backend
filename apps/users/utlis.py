import re
from typing import Optional
from django.conf import settings

PHONE_RE_KG = re.compile(r'^996\d{9}$')  

def normalize_phone(phone: str) -> str:
    digits = re.sub(r'\D+', '', str(phone or ''))
    if not PHONE_RE_KG.fullmatch(digits):
        raise ValueError("Формат телефона: 996XXXXXXXXX")
    return digits

def _norm(s: Optional[str]) -> Optional[str]:
    return re.sub(r'\D+', '', s) if s else None


def _static_otp_enabled() -> bool:
    return bool(
        settings.DEBUG
        or getattr(settings, "ENABLE_DEBUG_OTP_ENDPOINT", False)
        or getattr(settings, "ALLOW_STATIC_OTP_IN_PRODUCTION", False)
    )


def is_static_otp_phone(phone: str) -> bool:
    if not _static_otp_enabled():
        return False
    p = normalize_phone(phone)
    mapping = getattr(settings, "STATIC_OTP", None)
    if isinstance(mapping, dict):
        for k in mapping.keys():
            if _norm(k) == p:
                return True
    single = getattr(settings, "STATIC_OTP_PHONE", None)
    if _norm(single) == p:
        return True
    return bool(str(getattr(settings, "STATIC_OTP_CODE", "") or "").strip())


def static_otp_for(phone: str) -> Optional[str]:
    if not _static_otp_enabled():
        return None
    p = normalize_phone(phone)
    mapping = getattr(settings, "STATIC_OTP", None)
    if isinstance(mapping, dict):
        for k, v in mapping.items():
            if _norm(k) == p:
                return str(v)
    code = str(getattr(settings, "STATIC_OTP_CODE", "") or "").strip()
    return code or None
