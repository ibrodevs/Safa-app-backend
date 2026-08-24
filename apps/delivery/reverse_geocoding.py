from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def _cache_key(lat: float, lon: float) -> str:
    return f"reverse-geocode:v2:{lat:.4f}:{lon:.4f}"


def _yandex_address(lat: float, lon: float) -> str:
    api_key = str(getattr(settings, "YANDEX_API_KEY", "") or "").strip()
    if not api_key:
        return ""
    response = requests.get(
        "https://geocode-maps.yandex.ru/1.x/",
        params={
            "apikey": api_key,
            "geocode": f"{lon},{lat}",
            "format": "json",
            "lang": "ru_RU",
        },
        timeout=7,
    )
    response.raise_for_status()
    members = response.json()["response"]["GeoObjectCollection"]["featureMember"]
    if not members:
        return ""
    return str(
        members[0]["GeoObject"]["metaDataProperty"]["GeocoderMetaData"]["text"]
    ).strip()


def _nominatim_address(lat: float, lon: float) -> str:
    user_agent = str(
        getattr(settings, "GEOCODER_USER_AGENT", "SAFA/1.0") or "SAFA/1.0"
    ).strip()
    contact_email = str(getattr(settings, "GEOCODER_CONTACT_EMAIL", "") or "").strip()
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "accept-language": "ru",
        "zoom": 18,
        "addressdetails": 1,
    }
    if contact_email:
        params["email"] = contact_email
    response = requests.get(
        "https://nominatim.openstreetmap.org/reverse",
        params=params,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        timeout=7,
    )
    response.raise_for_status()
    return str(response.json().get("display_name") or "").strip()


def reverse_geocode_address(lat: float, lon: float) -> tuple[str, str] | None:
    """Resolve a readable address with cache and provider failover."""

    key = _cache_key(lat, lon)
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("address"):
        return str(cached["address"]), str(cached.get("source") or "cache")

    providers = (
        ("yandex", _yandex_address),
        ("openstreetmap", _nominatim_address),
    )
    for source, resolver in providers:
        try:
            address = resolver(lat, lon)
        except requests.RequestException:
            logger.warning("reverse_geocode_provider_unavailable", extra={"provider": source})
            continue
        except (KeyError, TypeError, ValueError):
            logger.warning("reverse_geocode_provider_invalid_response", extra={"provider": source})
            continue
        if not address:
            continue
        cache.set(
            key,
            {"address": address, "source": source},
            timeout=60 * 60 * 24 * 7,
        )
        return address, source
    return None
