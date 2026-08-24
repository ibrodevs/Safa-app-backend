# apps/notifications/serializers.py
from __future__ import annotations

from rest_framework import serializers

from apps.users.enrollment import (
    InvalidKYCEnrollmentToken,
    user_from_kyc_enrollment_token,
)
from apps.users.models import CourierKYC, User

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


class PendingKYCFCMTokenSerializer(serializers.ModelSerializer):
    kyc_token = serializers.CharField(write_only=True)

    class Meta:
        model = FCMToken
        fields = ("token", "platform", "device_id", "kyc_token")

    def validate_kyc_token(self, value):
        try:
            user = user_from_kyc_enrollment_token(value)
        except InvalidKYCEnrollmentToken:
            raise serializers.ValidationError("invalid_kyc_token")
        kyc = getattr(user, "kyc", None)
        if user.role != User.Roles.CARRIER or not isinstance(kyc, CourierKYC):
            raise serializers.ValidationError("invalid_kyc_token")
        self.context["kyc_user"] = user
        return value

    def create(self, validated_data):
        validated_data.pop("kyc_token", None)
        obj, _ = FCMToken.objects.update_or_create(
            token=validated_data["token"],
            defaults={
                "user": self.context["kyc_user"],
                "platform": validated_data.get(
                    "platform", FCMToken.Platform.ANDROID
                ),
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
