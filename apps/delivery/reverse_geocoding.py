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
    "kyrgyzstan",
    "kazakhstan",
    "russia",
    "uzbekistan",
    "tajikistan",
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

    meta = (
        geo_object.get("metaDataProperty", {})
        .get("GeocoderMetaData", {})
    )
    text = clean_address(meta.get("text", ""))

    locality = components.get("locality") or components.get("area") or "Бишкек"
    district = components.get("district") or ""
    street = components.get("street") or components.get("route") or ""
    house = components.get("house") or ""
    landmark = str(geo_object.get("name") or "").strip()

    is_dordoi = (
        (42.925 <= lat <= 42.955 and 74.605 <= lon <= 74.650)
        or "дордой" in text.lower()
        or "проход" in text.lower()
        or "дордой" in district.lower()
        or "проход" in street.lower()
    )

    if is_dordoi:
        parts = []
        p_match = re.search(r"((?:проход\s+[0-9a-zA-Zа-яА-Я]+|\d+[-–—]?(?:й|ой|ий|ый)?\s*проход|проход\s*Центральный))", text, re.IGNORECASE)
        passage = p_match.group(1) if p_match else (street if "проход" in street.lower() else "")
        if not passage and "проход" in landmark.lower():
            passage = landmark

        h_match = re.search(r"\b(\d+(?:[/-]\d+)?)\b", house or landmark or text)
        house_num = house or (h_match.group(1) if h_match else "")

        if passage:
            parts.append(passage)
        elif street:
            parts.append(street)

        if house_num and house_num not in (parts[0] if parts else ""):
            parts.append(house_num)

        for sm in ["Мурас-Спорт", "Алкан", "Европа", "Оберон", "Джунхай", "Кербен", "Ак-Суу", "Север", "Восток"]:
            if sm.lower() in text.lower() and not any(sm.lower() in p.lower() for p in parts):
                parts.append(f"рынок {sm}")
                break

        parts.append("рынок Дордой")
        parts.append("Бишкек")
        return ", ".join([p for p in parts if p])

    parts = []
    if street and house:
        parts.append(f"{street}, {house}")
    elif street:
        parts.append(street)
    elif district:
        parts.append(district)
    elif landmark:
        parts.append(landmark)

    parts.append("Бишкек")
    return ", ".join([p for p in parts if p])


def _nominatim_compose(payload: dict, lat: float = 0.0, lon: float = 0.0) -> str:
    address = payload.get("address")
    if not isinstance(address, dict):
        return clean_address(str(payload.get("display_name") or ""))

    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or "Бишкек"
    )
    if "бишкек" in city.lower():
        city = "Бишкек"

    road = (address.get("road") or address.get("pedestrian") or "").strip()
    house = (address.get("house_number") or "").strip()
    suburb = (
        address.get("suburb")
        or address.get("neighbourhood")
        or address.get("residential")
        or address.get("quarter")
        or ""
    ).strip()
    place = (
        address.get("shop")
        or address.get("amenity")
        or address.get("marketplace")
        or address.get("commercial")
        or ""
    ).strip()

    is_dordoi = (
        (42.925 <= lat <= 42.955 and 74.605 <= lon <= 74.650)
        or "дордой" in suburb.lower()
        or "проход" in road.lower()
        or "дордой" in place.lower()
    )

    if is_dordoi:
        parts = []
        if road:
            parts.append(road)
        elif place and "дордой" not in place.lower():
            parts.append(place)
        elif suburb and "дордой" not in suburb.lower():
            parts.append(suburb)

        if house and not any(house in p for p in parts):
            parts.append(house)

        submarket = ""
        for cand in [place, suburb]:
            c_low = cand.lower()
            if cand and "дордой" not in c_low and "бишкек" not in c_low and cand != road:
                submarket = cand
                break
        if submarket:
            sub_clean = submarket if submarket.lower().startswith("рынок") else f"рынок {submarket}"
            if sub_clean not in parts:
                parts.append(sub_clean)

        parts.append("рынок Дордой")
        parts.append("Бишкек")
        return ", ".join([p for p in parts if p])

    parts = []
    if city:
        parts.append(city)
    if road and house:
        parts.append(f"{road}, {house}")
    elif road:
        parts.append(road)
    elif place:
        parts.append(place)
    elif suburb:
        parts.append(suburb)

    return ", ".join([p for p in parts if p])


def _nominatim_address(lat: float, lon: float) -> str:
    user_agent = str(
        getattr(settings, "GEOCODER_USER_AGENT", "SAFA-App/1.0 (contact: senya.kalchoroev@gmail.com)") or "SAFA-App/1.0"
    ).strip()
    contact_email = str(getattr(settings, "GEOCODER_CONTACT_EMAIL", "senya.kalchoroev@gmail.com") or "senya.kalchoroev@gmail.com").strip()
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
    return _nominatim_compose(payload, lat=lat, lon=lon).strip()


def _yandex_web_address(lat: float, lon: float) -> str:
    url = f"https://yandex.ru/maps/?ll={lon}%2C{lat}&mode=search&sll={lon}%2C{lat}&text={lat}%2C{lon}&z=19"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            html = response.text
            m = re.search(r'<meta\s+itemProp="description"\s+content="([^"]+)"', html)
            if m:
                val = m.group(1).strip()
                if val:
                    return val
            m2 = re.search(r'class="toponym-card-title-view__description">([^<]+)</div>', html)
            if m2:
                val = m2.group(1).strip()
                if val:
                    return val
    except Exception as e:
        logger.warning("yandex_web_reverse_failed", extra={"error": str(e)})
    return ""


def reverse_geocode_address(lat: float, lon: float) -> tuple[str, str] | None:
    """Resolve a readable address with cache and provider failover."""

    key = _cache_key(lat, lon)
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("address"):
        return str(cached["address"]), str(cached.get("source") or "cache")

    providers = (
        ("yandex_web", _yandex_web_address),
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
