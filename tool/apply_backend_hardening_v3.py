from pathlib import Path


def replace_required(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_required(
    "apps/delivery/serializer.py",
    '''class ShipmentDetailSerializer(serializers.ModelSerializer):
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)
    commission = serializers.SerializerMethodField()
    courier_income = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = [
            "id",
            "public_code",
            "status",
            "title",
            "service_type",
            "description",
            "stops",
''',
    '''class ShipmentDetailSerializer(serializers.ModelSerializer):
    stops = ShipmentStopReadSerializer(many=True, read_only=True)
    stops_count = serializers.SerializerMethodField()
    public_code = serializers.CharField(read_only=True)
    commission = serializers.SerializerMethodField()
    courier_income = serializers.SerializerMethodField()

    class Meta:
        model = Shipment
        fields = [
            "id",
            "public_code",
            "status",
            "title",
            "service_type",
            "description",
            "client_id",
            "carrier_id",
            "current_stop_index",
            "stops",
''',
)

replace_required(
    "apps/delivery/views.py",
    '''        if s.carrier_id and s.carrier_id != request.user.id and not request.user.is_staff:
            return response.Response({"detail": "only_assigned_carrier"}, status=status.HTTP_403_FORBIDDEN)
''',
    '''        if (
            s.carrier_id
            and s.carrier_id != request.user.id
            and s.client_id != request.user.id
            and not request.user.is_staff
        ):
            return response.Response({"detail": "only_assigned_carrier"}, status=status.HTTP_403_FORBIDDEN)
''',
)

print("Backend hardening patch v3 applied")
