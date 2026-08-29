from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

import requests

logger = logging.getLogger(__name__)

# NOTE: This module is intentionally importable from serializers (no DRF/Django imports)

UA = {"User-Agent": "SAFA-App/1.0 (contact: senya.kalchoroev@gmail.com)"}

# TODO: move to env/config when project wiring allows.
TWOGIS_API_KEY = "c65e5972-5592-4197-9dd2-e43bdcfd83fd"


# Дордой (центр + ограничение по радиусу для более точного поиска)
DORDOI_LON = 74.6217
DORDOI_LAT = 42.9367
DORDOI_RADIUS = 4000


_MARKET_WORDS = (
    "дордой",
    "рынок дордой",
    "мурас спорт",
    "алкан базары",
    "рынок",
    "базар",
    "базары",
)

_RE_PASSAGE = re.compile(r"(\d+)\s*[-–]?\s*й?\s*проход", re.IGNORECASE)
_RE_CONTAINER = re.compile(r"контейнер\s+(\d+)", re.IGNORECASE)


def _split_market_container_passage(title: str, address: str) -> Tuple[str | None, str | None, str | None]:
    """Пытаемся извлечь market/container/passage из 2ГИС name/address."""
    full = f"{title}, {address}".strip(", ")

    market: str | None = None
    container: str | None = None
    passage: str | None = None

    parts = [p.strip() for p in full.split(",") if p.strip()]
    markets = [p for p in parts if any(w in p.lower() for w in _MARKET_WORDS)]
    if markets:
        market = markets[-1]

    m = _RE_CONTAINER.search(full)
    if m:
        container = m.group(1)

    m = _RE_PASSAGE.search(full)
    if m:
        passage = m.group(1)

    return market, container, passage


def _build_query_text(
    market: str | None,
    container: str | None,
    passage: str | None,
    q: str | None,
) -> str | None:
    market = (market or "").strip()
    container = (container or "").strip()
    passage = (passage or "").strip()
    q = (q or "").strip()

    # Если маркет не указан, но указали контейнер/проход — ограничиваем Дордоем.
    if not market and (container or passage):
        market = "Рынок Дордой"

    if market:
        parts = [market]
        if container:
            parts.append(f"контейнер {container}")
        if passage:
            parts.append(f"{passage} проход")
        # если при этом пришёл q — добавим в конец (иногда содержит подсказки)
        if q:
            parts.append(q)
        return ", ".join([p for p in parts if p])

    if q:
        return q

    return None


def _search_nominatim_bishkek(q: str, limit: int = 10) -> List[Dict]:
    """Search Bishkek addresses via Nominatim in Russian."""
    query = (q or "").strip()
    if not query:
        return []
    # If query does not mention Bishkek, prepend it for exact city relevance
    search_q = query if "бишкек" in query.lower() else f"Бишкек {query}"
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": search_q,
        "format": "jsonv2",
        "accept-language": "ru",
        "addressdetails": 1,
        "countrycodes": "kg",
        "viewbox": "74.45,42.99,74.75,42.75",
        "limit": limit,
        "email": "senya.kalchoroev@gmail.com",
    }
    try:
        r = requests.get(url, params=params, headers=UA, timeout=5)
        if r.status_code != 200:
            return []
        items = r.json()
        if not isinstance(items, list):
            return []
        results = []
        for item in items:
            addr = item.get("address", {})
            road = (addr.get("road") or addr.get("pedestrian") or "").strip()
            house = (addr.get("house_number") or "").strip()
            city = (addr.get("city") or addr.get("town") or "Бишкек").strip()
            name = (item.get("name") or road).strip()
            place = (addr.get("shop") or addr.get("amenity") or addr.get("marketplace") or addr.get("suburb") or "").strip()

            parts = [p for p in [road or place, house, city] if p]
            title = f"{road} {house}".strip() if (road and house) else (road or name or place or item.get("display_name", ""))
            full_addr = ", ".join(parts) if parts else item.get("display_name", "")

            results.append(
                {
                    "title": title or full_addr,
                    "address": full_addr,
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                }
            )
        return results
    except Exception:
        return []


def twogis_autocomplete(
    *,
    market: str | None = None,
    container: str | None = None,
    passage: str | None = None,
    q: str | None = None,
    page_size: int = 10,
    timeout_s: int = 5,
) -> List[Dict]:
    """Автодополнение адресов по городу Бишкек и карте."""
    query_text = (q or _build_query_text(market, container, passage, q) or "").strip()
    if not query_text:
        return []

    page_size = max(1, min(int(page_size or 10), 20))
    results: List[Dict] = []
    seen_coords = set()

    # Поиск по реальным адресам города Бишкек
    city_results = _search_nominatim_bishkek(query_text, limit=page_size)
    for res in city_results:
        key = (round(res["lat"], 4), round(res["lon"], 4))
        if key not in seen_coords:
            seen_coords.add(key)
            results.append(res)
        if len(results) >= page_size:
            break

    return results[:page_size]


class GeocodeNotFound(Exception):
    pass


def twogis_resolve_best(
    *,
    market: str | None = None,
    container: str | None = None,
    passage: str | None = None,
    q: str | None = None,
    page_size: int = 5,
) -> Dict:
    """Вернуть лучший результат (первый) с координатами."""
    results = twogis_autocomplete(
        market=market,
        container=container,
        passage=passage,
        q=q,
        page_size=page_size,
    )

    for r in results:
        if r.get("lat") is not None and r.get("lon") is not None:
            return r

    raise GeocodeNotFound("not_found")
