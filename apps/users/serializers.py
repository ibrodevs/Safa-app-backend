from rest_framework import serializers
from django.db import IntegrityError, transaction
from apps.users.models import *
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .enrollment import (
    InvalidKYCEnrollmentToken,
    make_kyc_enrollment_token,
    user_from_kyc_enrollment_token,
)

phone_re = RegexValidator(
    regex=r'^996\d{9}$',
    message="Формат телефона: 996XXXXXXXXX (Кыргызстан)."
)

def _abs_url(request, field):
    if not field:
        return None
    url = field.url
    if request:
        return request.build_absolute_uri(url)
    return url


class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'role', 'specialist_type', 'first_name', 'phone_number', 'city', 'avatar', 'avatar_url')
        read_only_fields = ('id', 'role', 'phone_number', 'avatar_url')

    def get_avatar_url(self, obj):
        return _abs_url(self.context.get("request"), getattr(obj, "avatar", None))

    def get_kyc(self, obj):
        if obj.role != User.Roles.CARRIER:
            return None
        kyc = getattr(obj, "kyc", None)
        return CourierKYCSerializer(kyc, context=self.context).data if kyc else {
            "status": CourierKYC.Status.PENDING,
            "comment": "",
            "checked_at": None,
            "id_front": None,
            "id_back": None,
            "selfie_id_card": None,
        }



class RegisterSerializer(serializers.ModelSerializer):
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

    kyc_token = serializers.SerializerMethodField(read_only=True)
    id_front = serializers.ImageField(write_only=True, required=False, allow_null=True)
    id_back  = serializers.ImageField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True, min_length=6, required=True)
    password_confirm = serializers.CharField(write_only=True, required=True)

    def _validate_image_size(self, image, field_name):
        if image and hasattr(image, "size") and image.size > self.MAX_IMAGE_SIZE:
            raise serializers.ValidationError(
                f"Размер файла {field_name} не должен превышать 10 МБ."
            )
        return image

    def validate_id_front(self, value):
        return self._validate_image_size(value, "id_front")

    def validate_id_back(self, value):
        return self._validate_image_size(value, "id_back")

    class Meta:
        model = User
        fields = (
            "phone_number", "first_name", "avatar",
            "role", "specialist_type", "id_front", "id_back", "password", "password_confirm",
            "kyc_token",
        )
        extra_kwargs = {
            "phone_number": {"validators": [phone_re]},
            "avatar": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        password = attrs.get("password")
        password_confirm = attrs.pop("password_confirm", None)
        if password != password_confirm:
            raise serializers.ValidationError({"password_confirm": "Пароли не совпадают."})

        role = attrs.get("role", User.Roles.CLIENT)
        if role == User.Roles.CARRIER:
            attrs["specialist_type"] = attrs.get("specialist_type") or User.SpecialistType.DELIVERY
            if not attrs.get("id_front") or not attrs.get("id_back"):
                raise serializers.ValidationError(
                    {"non_field_errors": ["Для перевозчика загрузите лицевую и обратную сторону документа."]}
                )
        return attrs

    def validate_phone_number(self, value):
        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("Пользователь с таким номером уже зарегистрирован.")
        return value

    def create(self, validated_data):
        id_front = validated_data.pop("id_front", None)
        id_back  = validated_data.pop("id_back", None)
        password = validated_data.pop("password")

        with transaction.atomic():
            user = User(**validated_data)
            user.set_password(password)

            from apps.users.utlis import is_static_otp_phone
            if is_static_otp_phone(user.phone_number):
                user.is_verify = True
            if user.role == User.Roles.CARRIER:
                user.is_active = False
            
            try:
                user.save()
            except IntegrityError:
                raise serializers.ValidationError(
                    {"phone_number": "Пользователь с таким номером уже зарегистрирован."}
                )

            if user.role == User.Roles.CARRIER:
                kyc, _ = CourierKYC.objects.get_or_create(user=user)
                changed = []

                if id_front is not None:
                    kyc.id_front = id_front
                    changed.append("id_front")

                if id_back is not None:
                    kyc.id_back = id_back
                    changed.append("id_back")

                if kyc.status != CourierKYC.Status.PENDING:
                    kyc.status = CourierKYC.Status.PENDING
                    changed.append("status")
                if kyc.checked_at is not None:
                    kyc.checked_at = None
                    changed.append("checked_at")

                if changed:
                    kyc.save(update_fields=changed)

        return user

    def get_kyc_token(self, obj) -> str | None:
        if obj.role != User.Roles.CARRIER:
            return None
        return make_kyc_enrollment_token(obj)


class VerifiedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Password login is available only after phone/KYC verification."""

    def validate(self, attrs):
        phone = attrs.get(self.username_field)
        candidate = User.objects.filter(phone_number=phone).first()
        if candidate and candidate.check_password(attrs.get("password") or ""):
            if not candidate.is_verify:
                raise AuthenticationFailed("phone_not_verified")
            if candidate.role == User.Roles.CARRIER:
                kyc = getattr(candidate, "kyc", None)
                if not kyc or kyc.status != CourierKYC.Status.APPROVED:
                    raise AuthenticationFailed("specialist_not_approved")
        return super().validate(attrs)




MAX_MB = 32



class SelfieWithIdCardSerializer(serializers.Serializer):
    phone = serializers.CharField(write_only=True, validators=[phone_re])
    kyc_token = serializers.CharField(write_only=True)
    selfie_id_card = serializers.ImageField(required=True, write_only=True)

    def validate_phone(self, value):
        from apps.users.utlis import normalize_phone
        try:
            return normalize_phone(value)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

    def validate_selfie_id_card(self, f):
        if f.size > MAX_MB * 1024 * 1024:
            raise serializers.ValidationError(f"Файл больше {MAX_MB} МБ")
        if not f.content_type.startswith("image/"):
            raise serializers.ValidationError("Нужна картинка (JPEG/PNG)")
        return f

    def create(self, validated_data):
        phone = validated_data["phone"]
        selfie = validated_data["selfie_id_card"]

        try:
            user = user_from_kyc_enrollment_token(validated_data["kyc_token"])
        except InvalidKYCEnrollmentToken:
            raise serializers.ValidationError({"kyc_token": "invalid_kyc_token"})
        if user.phone_number != phone:
            raise serializers.ValidationError({"kyc_token": "invalid_kyc_token"})

        kyc, _ = CourierKYC.objects.get_or_create(user=user)
        kyc.selfie_id_card = selfie
        kyc.save(update_fields=["selfie_id_card"])
        return kyc

    def to_representation(self, instance):
        request = self.context.get("request")
        url = instance.selfie_id_card.url if instance.selfie_id_card else None
        if url and request:
            url = request.build_absolute_uri(url)
        return {
            "phone": instance.user.phone_number,
            "selfie_id_card": url,
        }




class RequestCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(validators=[phone_re])

class VerifyCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(validators=[phone_re])
    code  = serializers.CharField(max_length=8)



class UserProfileSerializer(serializers.ModelSerializer):
    role = serializers.CharField(source='user.role', read_only=True)
    specialist_type = serializers.CharField(source='user.specialist_type', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    first_name = serializers.CharField(source='user.first_name', required=False)
    avatar = serializers.ImageField(source='user.avatar', required=False, allow_null=True)
    avatar_url = serializers.SerializerMethodField()
    city = serializers.CharField(source='user.city', required=False)
    rate = serializers.FloatField(read_only=True)

    class Meta:
        model = UserProfile
        fields = (
            'role',
            'specialist_type',
            'phone_number',
            'first_name',
            'city',
            'avatar',
            'avatar_url',
            'rate',
            'client_rate_count',
            'created_at',
        )
        read_only_fields = ('rate', 'client_rate_count', 'created_at', 'avatar_url')

    def get_avatar_url(self, obj):
        user = getattr(obj, "user", None)
        return _abs_url(self.context.get("request"), getattr(user, "avatar", None)) if user else None

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if user_data:
            user = instance.user
            for attr, value in user_data.items():
                setattr(user, attr, value)
            user.save(update_fields=list(user_data.keys()))
        return instance


class CourierKYCSerializer(serializers.ModelSerializer):
    id_front = serializers.SerializerMethodField()
    id_back = serializers.SerializerMethodField()
    selfie_id_card = serializers.SerializerMethodField()

    class Meta:
        model = CourierKYC
        fields = ("status", "comment", "checked_at", "id_front", "id_back", "selfie_id_card")
        read_only_fields = fields

    def get_id_front(self, obj):
        return _abs_url(self.context.get("request"), obj.id_front)

    def get_id_back(self, obj):
        return _abs_url(self.context.get("request"), obj.id_back)

    def get_selfie_id_card(self, obj):
        return _abs_url(self.context.get("request"), obj.selfie_id_card)




class CarrierLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(validators=[phone_re])
    kyc_token = serializers.CharField(write_only=True)
