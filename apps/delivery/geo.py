from __future__ import annotations
from math import radians, sin, cos, asin, sqrt
from typing import Iterable, Tuple

EARTH_R_M = 6_371_000.0  

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * EARTH_R_M * asin(sqrt(a))

def polyline_len_km(points: Iterable[Tuple[float, float]]) -> float:
    pts = list(points)
    if len(pts) < 2:
        return 0.0
    total_m = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(pts, pts[1:]):
        total_m += haversine_m(lat1, lon1, lat2, lon2)
    return round(total_m / 1000.0, 2)

def bbox_deltas(lat: float, radius_m: int) -> tuple[float, float]:
    lat = float(lat)
    d_lat = radius_m / EARTH_R_M * 180.0 / 3.141592653589793
    denom = max(cos(radians(lat)), 1e-6)
    d_lon = radius_m / (EARTH_R_M * denom) * 180.0 / 3.141592653589793
    return d_lat, d_lon

BISHKEK_LAT = 42.8714
BISHKEK_LON = 74.5880
BISHKEK_RADIUS_M = 20_000

def is_in_bishkek(lat: float, lon: float) -> bool:
    return haversine_m(BISHKEK_LAT, BISHKEK_LON, lat, lon) <= BISHKEK_RADIUS_M
