from .models import GlobalDeliveryConfig
from decimal import Decimal, ROUND_HALF_UP

def estimate_fare(distance_km) -> int:
    distance_km = Decimal(distance_km)
    
    config = GlobalDeliveryConfig.get_config()
    base_price = Decimal(config.base_price)
    per_km_price = Decimal(config.per_km_price)
    min_fare = Decimal(config.min_fare)

    cost = base_price + per_km_price * distance_km
    cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    if cost < min_fare:
        cost = min_fare
        
    return int(cost.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
