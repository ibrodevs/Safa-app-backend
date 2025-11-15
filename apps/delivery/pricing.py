from decimal import Decimal, ROUND_HALF_UP

def size_multiplier(segment, size: str) -> Decimal:
    if size == "S":
        return Decimal(segment.size_s_multiplier or 1)
    if size == "L":
        return Decimal(segment.size_l_multiplier or 1)
    return Decimal(segment.size_m_multiplier or 1)

def estimate_fare(segment, distance_km, *, fragile: bool, size: str, quantity: int = 1) -> int:
    distance_km = Decimal(distance_km)
    base = Decimal(segment.base_price) + Decimal(segment.per_km_price) * distance_km
    mult = size_multiplier(segment, size)
    if fragile:
        mult *= (Decimal("1.00") + Decimal(segment.fragile_pct or 0) / Decimal("100"))
    cost = (base * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if segment.per_unit:
        cost *= Decimal(quantity or 1)
    min_fare = Decimal(segment.min_fare or 0)
    if cost < min_fare:
        cost = min_fare
    return int(cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
