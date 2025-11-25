# apps/notifications/serializers.py
from __future__ import annotations

from rest_framework import serializers

from .models import FCMToken, Notification


class FCMTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = FCMToken
        fields = ("token", "platform", "device_id")

    def create(self, validated_data):
        user = self.context["request"].user
        obj, _ = FCMToken.objects.update_or_create(
            token=validated_data["token"],
            defaults={
                "user": user,
                "platform": validated_data.get("platform", FCMToken.Platform.ANDROID),
                "device_id": validated_data.get("device_id", "") or "",
                "is_active": True,
            },
        )
        return obj


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            "id",
            "type",
            "channel",
            "title",
            "body",
            "data",
            "is_read",
            "created_at",
            "read_at",
        )
        read_only_fields = fields
