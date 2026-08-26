from __future__ import annotations

import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Названия стран и почтовые индексы в подписи точки не нужны: пользователь
# выбирает адрес внутри города, а не международную посылку.
_COUNTRY_NAMES = {
    "кыргызстан",
    "киргизия",
    "кыргызская республика",
    "казахстан",
    "россия",
    "российская федерация",
    "узбекистан",
    "таджикистан",
    "китай",
    "kyrgyzstan",
    "kazakhstan",
    "russia",
    "uzbekistan",
    "tajikistan",
    "china",
}

_POSTAL_CODE = re.compile(r"^\d{5,6}$")
_POSTAL_INSIDE = re.compile(r"(?<!\d)\d{6}(?!\d)")


def _is_noise_part(part: str) -> bool:
    """Почтовый индекс, страна или пустой фрагмент адреса."""

    value = part.strip().strip(",").strip()
    if not value:
        return True
    if _POSTAL_CODE.match(value):
        return True
    return value.casefold() in _COUNTRY_NAMES


def clean_address(raw: str) -> str:
    """Убирает из готовой строки адреса почтовый индекс и страну."""

    parts = [part.strip() for part in str(raw or "").split(",")]
    kept = [part for part in parts if not _is_noise_part(part)]
    # Индекс иногда приклеен к городу: «720000 Бишкек».
    kept = [_POSTAL_INSIDE.sub("", part).strip() for part in kept]
    return ", ".join(part for part in kept if part)


def _join_address(parts: list[str]) -> str:
    seen: list[str] = []
    for part in parts:
        value = str(part or "").strip()
        if not value or _is_noise_part(value):
            continue
        if value.casefold() in {item.casefold() for item in seen}:
            continue
        seen.append(value)
    return ", ".join(seen)


def _cache_key(lat: float, lon: float) -> str:
    # v3: адреса версий v1/v2 могли содержать почтовый индекс и страну.
    return f"reverse-geocode:v3:{lat:.4f}:{lon:.4f}"


def _yandex_components(geo_object: dict) -> dict[str, str]:
    address = (
        geo_object.get("metaDataProperty", {})
        .get("GeocoderMetaData", {})
        .get("Address", {})
    )
    components = address.get("Components") or []
    result: dict[str, str] = {}
    for component in components:
        kind = str(component.get("kind") or "").strip()
        name = str(component.get("name") or "").strip()
        if kind and name and kind not in result:
            result[kind] = name
    return result


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
            "results": 1,
        },
        timeout=7,
    )
    response.raise_for_status()
    members = response.json()["response"]["GeoObjectCollection"]["featureMember"]
    if not members:
        return ""

    geo_object = members[0]["GeoObject"]
    components = _yandex_components(geo_object)

    # Собираем адрес сами: «text» у Яндекса начинается со страны, а у части
    # объектов содержит и почтовый индекс.
    locality = components.get("locality") or components.get("area")
    district = components.get("district")
    street = components.get("street") or components.get("route")
    house = components.get("house")
    landmark = str(geo_object.get("name") or "").strip()

    composed = _join_address(
        [
            locality or "",
            district if not street else "",
            street or "",
            house or "",
        ]
    )
    if not composed:
        composed = _join_address([locality or "", landmark])
    if composed:
        return composed

    fallback = (
        geo_object.get("metaDataProperty", {})
        .get("GeocoderMetaData", {})
        .get("text", "")
    )
    return clean_address(fallback)


def _nominatim_compose(payload: dict) -> str:
    address = payload.get("address")
    if not isinstance(address, dict):
        return clean_address(str(payload.get("display_name") or ""))

    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or ""
    )
    street = address.get("road") or address.get("pedestrian") or ""
    house = address.get("house_number") or ""
    place = (
        address.get("shop")
        or address.get("amenity")
        or address.get("marketplace")
        or address.get("neighbourhood")
        or address.get("suburb")
        or ""
    )

    composed = _join_address([city, street, house]) if street else ""
    if not composed:
        composed = _join_address([city, place])
    if composed:
        return composed
    return clean_address(str(payload.get("display_name") or ""))


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
    payload = response.json()
    if not isinstance(payload, dict):
        return ""
    return _nominatim_compose(payload).strip()


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
        address = clean_address(address)
        if not address:
            continue
        cache.set(
            key,
            {"address": address, "source": source},
            timeout=60 * 60 * 24 * 7,
        )
        return address, source
    return None
