# apps/delivery/serializer.py
from __future__ import annotations
from rest_framework import serializers
from .models import Bazar, Container, CourierSegment, Shipment, ShipmentStop

class BazarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bazar
        fields = ["id", "name"]

class ContainerSerializer(serializers.ModelSerializer):
    bazar = BazarSerializer(read_only=True)
    # возвращаем lat/lon явно
    latitude  = serializers.FloatField(source="lat", read_only=True)
    longitude = serializers.FloatField(source="lon", read_only=True)

    class Meta:
        model = Container
        fields = ["id", "title", "number", "passage", "latitude", "longitude", "bazar"]

class CourierSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierSegment
        fields = [
            "id", "name", "slug", "is_active", "order", "icon",
            "base_price", "per_km_price", "min_fare",
            "fragile_pct", "size_s_multiplier", "size_m_multiplier", "size_l_multiplier",
            "per_unit",
        ]

class ShipmentStopReadSerializer(serializers.ModelSerializer):
    container = ContainerSerializer(read_only=True)
    class Meta:
        model = ShipmentStop
        fields = ["position", "container"]

class ShipmentCreateSerializer(serializers.ModelSerializer):
    stops = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=2, max_length=4, write_only=True)
    return_to_start = serializers.BooleanField(default=False, write_only=True)
    item_label = serializers.CharField(required=False, allow_blank=True)
    estimated_fare = serializers.IntegerField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "title", "segment", "size", "quantity", "fragile", "item_label", "description",
            "stops", "return_to_start", "estimated_fare",
        ]

    def validate(self, attrs):
        stops = attrs.get("stops") or []
        rts = attrs.get("return_to_start", False)
        if not isinstance(stops, list) or len(stops) < 2 or len(stops) > 4:
            raise serializers.ValidationError({"stops": "Нужно 2–4 точки."})
        if rts and len(stops) >= 4:
            raise serializers.ValidationError({"return_to_start": "С возвратом максимум 3 исходные точки."})
        return attrs

    def create(self, validated_data):
        from .models import ShipmentStop
        stops_ids = list(validated_data.pop("stops"))
        return_to_start = validated_data.pop("return_to_start", False)
        if return_to_start:
            stops_ids.append(stops_ids[0])

        shipment = Shipment(client=self.context["request"].user, **validated_data)
        shipment.save()

        ShipmentStop.objects.bulk_create([
            ShipmentStop(shipment=shipment, container_id=cid, position=i)
            for i, cid in enumerate(stops_ids)
        ])

        shipment.current_stop_index = 1
        shipment.estimate()
        shipment.save(update_fields=["distance_km", "estimated_fare", "current_stop_index"])
        return shipment

class ShipmentDetailSerializer(serializers.ModelSerializer):
    segment = CourierSegmentSerializer(read_only=True)
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    size_label = serializers.SerializerMethodField()
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "public_code", "status", "title", "client", "carrier",
            "segment", "size", "size_label", "quantity", "item_label", "fragile", "description",
            "stops", "stops_count", "distance_km", "estimated_fare", "final_fare",
            "current_stop_index", "eta_to_next_min", "created_at",
        ]
        read_only_fields = fields

    def get_size_label(self, obj):
        return {"S": "Маленькие", "M": "Средние", "L": "Большие"}.get(obj.size, obj.size)

    def get_stops_count(self, obj):
        return obj.stops.count()

class ShipmentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shipment
        fields = ["status"]

class CoordsSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lon = serializers.FloatField()

class QuoteInSerializer(serializers.Serializer):
    segment_id = serializers.IntegerField()
    size = serializers.ChoiceField(choices=["S", "M", "L"], default="M")
    fragile = serializers.BooleanField(default=False)
    quantity = serializers.IntegerField(min_value=1, default=1)
    container_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=2, max_length=4, required=False)
    stops = serializers.ListField(child=CoordsSerializer(), min_length=2, max_length=4, required=False)
    return_to_start = serializers.BooleanField(default=False)

    def validate(self, attrs):
        has_ids = attrs.get("container_ids") is not None
        has_coords = attrs.get("stops") is not None
        if has_ids == has_coords:
            raise serializers.ValidationError("Передай либо container_ids, либо stops (одно из).")
        route_len = len(attrs["container_ids"] if has_ids else attrs["stops"])
        if attrs.get("return_to_start") and route_len >= 4:
            raise serializers.ValidationError({"return_to_start": "С возвратом максимум 3 исходные точки."})
        return attrs

class QuoteOutSerializer(serializers.Serializer):
    distance_km = serializers.DecimalField(max_digits=7, decimal_places=2)
    estimated_fare = serializers.IntegerField()

class ShipmentCardSerializer(serializers.ModelSerializer):
    pickup = serializers.SerializerMethodField()
    stops_count = serializers.SerializerMethodField()
    size_label = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)

    class Meta:
        model = Shipment
        fields = ["id", "public_code", "title", "estimated_fare", "size_label", "quantity", "fragile", "stops_count", "pickup"]

    def get_pickup(self, obj):
        s = obj.stops.order_by("position").first()
        if not s:
            return None
        c = s.container
        return {"id": c.id, "title": c.title, "number": c.number, "passage": c.passage, "bazar": c.bazar.name}

    def get_stops_count(self, obj): return obj.stops.count()
    def get_size_label(self, obj): return {"S":"Маленькие","M":"Средние","L":"Большие"}.get(obj.size, obj.size)
