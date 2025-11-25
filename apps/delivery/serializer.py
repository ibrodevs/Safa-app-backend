from __future__ import annotations
from rest_framework import serializers
from .models import CourierSegment, Shipment, ShipmentStop


class CourierSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourierSegment
        fields = [
            "id", "name", "slug", "is_active", "order", "icon",
            "base_price", "per_km_price", "min_fare",
            "fragile_pct", "size_s_multiplier", "size_m_multiplier", "size_l_multiplier",
            "per_unit",
        ]

class ShipmentStopInSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    lat = serializers.FloatField()
    lon = serializers.FloatField()


class ShipmentStopReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentStop
        fields = ["position", "title", "lat", "lon"]


class ShipmentCreateSerializer(serializers.ModelSerializer):
    stops = serializers.ListField(
        child=ShipmentStopInSerializer(),
        min_length=2,
        max_length=4,
        write_only=True,
    )
    return_to_start = serializers.BooleanField(default=False, write_only=True)
    estimated_fare = serializers.IntegerField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "title", "segment", "size", "quantity",
            "fragile", "description",
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

        stops_data = list(validated_data.pop("stops"))
        return_to_start = validated_data.pop("return_to_start", False)
        if return_to_start and stops_data:
            stops_data.append(stops_data[0])

        shipment = Shipment(client=self.context["request"].user, **validated_data)
        shipment.save()

        ShipmentStop.objects.bulk_create([
            ShipmentStop(
                shipment=shipment,
                position=i,
                title=stop["title"],
                lat=stop["lat"],
                lon=stop["lon"],
            )
            for i, stop in enumerate(stops_data)
        ])

        shipment.current_stop_index = 1
        shipment.estimate()
        shipment.save(update_fields=["distance_km", "estimated_fare", "current_stop_index"])
        return shipment



class ShipmentDetailSerializer(serializers.ModelSerializer):
    segment = CourierSegmentSerializer(read_only=True)
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id",
            "public_code",
            "status",
            "title",
            "segment",
            "size",
            "quantity",
            "fragile",
            "description",
            "stops",
            "stops_count",
            "estimated_fare",
            "final_fare",
            "created_at",
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
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    lat = serializers.FloatField()
    lon = serializers.FloatField()

class QuoteInSerializer(serializers.Serializer):
    segment_id = serializers.IntegerField()
    size = serializers.ChoiceField(choices=["S", "M", "L"], default="M")
    fragile = serializers.BooleanField(default=False)
    quantity = serializers.IntegerField(min_value=1, default=1)
    stops = serializers.ListField(child=CoordsSerializer(), min_length=2, max_length=4)
    return_to_start = serializers.BooleanField(default=False)

    def validate(self, attrs):
        stops = attrs.get("stops") or []
        if len(stops) < 2:
            raise serializers.ValidationError({"stops": "Нужно 2–4 точки."})
        if attrs.get("return_to_start") and len(stops) >= 4:
            raise serializers.ValidationError({"return_to_start": "С возвратом максимум 3 исходные точки."})
        return attrs

class QuoteOutSerializer(serializers.Serializer):
    distance_km = serializers.DecimalField(max_digits=7, decimal_places=2)
    estimated_fare = serializers.IntegerField()


class ShipmentCardSerializer(serializers.ModelSerializer):
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "public_code", "title", "estimated_fare",
            "quantity", "fragile",
            "stops_count", "status", "created_at",
        ]

    def get_stops_count(self, obj):
        return obj.stops.count()

    def get_size_label(self, obj):
        return {"S": "Маленькие", "M": "Средние", "L": "Большие"}.get(obj.size, obj.size)
