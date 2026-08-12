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

def is_static_otp_phone(phone: str) -> bool:
    if not settings.DEBUG and not getattr(
        settings, "ENABLE_DEBUG_OTP_ENDPOINT", False
    ):
        return False
    p = normalize_phone(phone)
    mapping = getattr(settings, "STATIC_OTP", None)
    if isinstance(mapping, dict):
        for k in mapping.keys():
            if _norm(k) == p:
                return True
    single = getattr(settings, "STATIC_OTP_PHONE", None)
    return _norm(single) == p

def static_otp_for(phone: str) -> Optional[str]:
    p = normalize_phone(phone)
    mapping = getattr(settings, "STATIC_OTP", None)
    if isinstance(mapping, dict):
        for k, v in mapping.items():
            if _norm(k) == p:
                return str(v)
    code = getattr(settings, "STATIC_OTP_CODE", None)
    return str(code) if code else None
