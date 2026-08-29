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


def _parse_dordoi_query(q: str) -> Dict | None:
    q_clean = q.strip()
    dordoi_keywords = [
        "проход",
        "ряд",
        "контейнер",
        "дордой",
        "мурас",
        "алкан",
        "европа",
        "оберон",
        "джунхай",
        "кербен",
        "ак-суу",
        "север",
        "восток",
        "центральный",
        "кишка",
    ]
    is_dordoi = any(kw in q_clean.lower() for kw in dordoi_keywords) or bool(
        re.search(r"\b\d+\s*[-/]?\s*проход\b|\bпроход\s*\d+\b", q_clean, re.I)
    )

    if not is_dordoi:
        m = re.match(r"^(\d+)\s*[,/ -]\s*(\d+)(?:[/ -](\d+))?$", q_clean)
        if m:
            is_dordoi = True

    if not is_dordoi:
        return None

    # Extract sector if mentioned
    sector = ""
    for s in [
        "мурас-спорт",
        "мурас спорт",
        "китай",
        "алкан",
        "алканов",
        "европа",
        "оберон",
        "джунхай",
        "кербен",
        "ак-суу",
        "восток",
        "север",
        "автозапчасти",
    ]:
        if s in q_clean.lower():
            if "мурас" in s:
                s_title = "Мурас-Спорт"
            elif "алкан" in s:
                s_title = "Алкан"
            elif "ак-суу" in s:
                s_title = "Ак-Суу"
            else:
                s_title = s.capitalize()
            sector = f"рынок {s_title}"
            break

    # Extract passage
    passage = ""
    m_pass = re.search(
        r"(\d+)(?:[-–—]?(?:й|ой|ий|ый))?\s*проход|проход\s*(?:№\s*)?([0-9a-zA-Zа-яА-Я]+)",
        q_clean,
        re.I,
    )
    if m_pass:
        p_num = m_pass.group(1) or m_pass.group(2)
        passage = f"{p_num}-й проход" if p_num.isdigit() else f"проход {p_num}"
    elif "центральный" in q_clean.lower():
        passage = "проход Центральный"

    # Extract container number
    rem = q_clean
    if passage:
        rem = re.sub(
            r"(?:\d+[-–—]?(?:й|ой|ий|ый)?\s*проход|проход\s*[0-9a-zA-Zа-яА-Я]+|проход|центральный)",
            "",
            rem,
            flags=re.I,
        )
    if sector:
        rem = re.sub(
            r"мурас[- ]?спорт|алкан(?:ов)?|европа|оберон|джунхай|кербен|ак-суу|восток|север|автозапчасти",
            "",
            rem,
            flags=re.I,
        )
    rem = re.sub(r"контейнер|дордой|рынок", "", rem, flags=re.I).strip(" ,.-/")
    container = rem.strip() if rem else ""

    if not passage and not container:
        m = re.match(r"^(\d+)\s*[,/ -]\s*(\d+)(?:[/ -](\d+))?$", q_clean)
        if m:
            container = m.group(1)
            passage = f"{m.group(2)}-й проход"
            if m.group(3):
                container = f"{container}/{m.group(3)}"

    parts = []
    if passage:
        parts.append(passage)
    if container:
        parts.append(container)
    if sector:
        parts.append(sector)
    parts.append("рынок Дордой")
    parts.append("Бишкек")

    title_parts = [p for p in [passage, container, sector] if p]
    title = ", ".join(title_parts) if title_parts else "рынок Дордой"
    full_addr = ", ".join(parts)

    return {
        "title": title,
        "address": full_addr,
        "lat": 42.9367,
        "lon": 74.6217,
    }


def twogis_autocomplete(
    *,
    market: str | None = None,
    container: str | None = None,
    passage: str | None = None,
    q: str | None = None,
    page_size: int = 10,
    timeout_s: int = 5,
) -> List[Dict]:
    """Автодополнение адресов по рынку Дордой и городу Бишкек."""
    query_text = (q or _build_query_text(market, container, passage, q) or "").strip()
    if not query_text:
        return []

    page_size = max(1, min(int(page_size or 10), 20))
    results: List[Dict] = []
    seen_addresses = set()

    # 1. Если это запрос по Дордою (проход/контейнер/сектор) — сразу формируем точный адрес
    dordoi_res = _parse_dordoi_query(query_text)
    if dordoi_res is not None:
        seen_addresses.add(dordoi_res["address"])
        results.append(dordoi_res)

    # 2. Поиск по реальным адресам города Бишкек
    city_results = _search_nominatim_bishkek(query_text, limit=page_size)
    for res in city_results:
        # Убираем дублирование слова Бишкек в конце
        addr = res["address"]
        if addr not in seen_addresses:
            seen_addresses.add(addr)
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
