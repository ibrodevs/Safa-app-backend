from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

import requests

logger = logging.getLogger(__name__)

# NOTE: This module is intentionally importable from serializers (no DRF/Django imports)

UA = {"User-Agent": "dordoi-go/1.0 (+contact@example.com)"}

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


def twogis_autocomplete(
    *,
    market: str | None = None,
    container: str | None = None,
    passage: str | None = None,
    q: str | None = None,
    page_size: int = 5,
    timeout_s: int = 5,
) -> List[Dict]:
    """Автодополнение по 2ГИС в районе Дордоя."""
    query_text = _build_query_text(market, container, passage, q)
    if not query_text:
        return []

    # защита от слишком больших page_size
    page_size = max(1, min(int(page_size or 5), 20))

    url = "https://catalog.api.2gis.com/3.0/items/geocode"
    params = {
        "key": TWOGIS_API_KEY,
        "q": query_text,
        "fields": "items.point,items.full_address_name",
        "page_size": page_size,
        "point": f"{DORDOI_LON},{DORDOI_LAT}",
        "radius": DORDOI_RADIUS,
        "sort": "distance",
        "search_nearby": "true",
        "locale": "ru_KG",
    }

    try:
        r = requests.get(url, params=params, headers=UA, timeout=timeout_s)
    except requests.RequestException:
        logger.exception("2gis_request_failed")
        raise

    r.raise_for_status()
    data = r.json()

    items = (data.get("result") or {}).get("items") or []
    results: List[Dict] = []

    for item in items:
        name = item.get("name") or ""
        addr = item.get("full_address_name") or ""
        point = item.get("point") or {}
        lon = point.get("lon")
        lat = point.get("lat")

        mkt, cont, pas = _split_market_container_passage(name, addr)

        results.append(
            {
                "title": name or addr,
                "address": addr,
                "market": mkt,
                "container": cont,
                "passage": pas,
                "lat": lat,
                "lon": lon,
            }
        )

    return results


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
