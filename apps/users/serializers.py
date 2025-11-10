from rest_framework import serializers
from apps.users.models import *

phone_re = RegexValidator(
    regex=r'^996\d{9}$',
    message="Формат телефона: 996XXXXXXXXX (Кыргызстан)."
)

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'role', 'first_name', 'last_name', 'phone_number')
        read_only_fields = ('id', 'role', 'phone_number')

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
    id_front = serializers.ImageField(write_only=True, required=False, allow_null=True)
    id_back  = serializers.ImageField(write_only=True, required=False, allow_null=True)
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = (
            "phone_number", "first_name", "last_name", "avatar",
            "role", "password", "password_confirm", "id_front", "id_back"
        )
        extra_kwargs = {
            "email": {"required": False, "allow_blank": True, "allow_null": True},
            "avatar": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        pwd = attrs.get("password")
        pwd2 = attrs.get("password_confirm")
        if pwd != pwd2:
            raise serializers.ValidationError({"password_confirm": "Пароли не совпадают."})

        role = attrs.get("role", User.Roles.CLIENT)
        if role == User.Roles.CARRIER:
            if not attrs.get("id_front") or not attrs.get("id_back"):
                raise serializers.ValidationError(
                    {"non_field_errors": ["Для перевозчика загрузите лицевую и обратную сторону документа."]}
                )

        attrs.pop("password_confirm", None)
        return attrs

    def create(self, validated_data):
        id_front = validated_data.pop("id_front", None)
        id_back  = validated_data.pop("id_back", None)
        password = validated_data.pop("password")

        user = User.objects.create_user(password=password, **validated_data)

        if user.role == User.Roles.CARRIER:
            kyc, _ = CourierKYC.objects.get_or_create(user=user)
            if id_front:
                kyc.id_front = id_front
            if id_back:
                kyc.id_back = id_back
            kyc.status = CourierKYC.Status.PENDING
            kyc.save()

        return user


MAX_MB = 32

class SelfieWithIdCardSerializer(serializers.Serializer):
    selfie_id_card = serializers.ImageField(required=True, write_only=True)

    def validate_selfie_id_card(self, f):
        if f.size > MAX_MB * 1024 * 1024:
            raise serializers.ValidationError(f"Файл больше {MAX_MB} МБ")
        if not f.content_type.startswith("image/"):
            raise serializers.ValidationError("Нужна картинка (JPEG/PNG)")
        return f

    def create(self, validated_data):
        user = self.context["request"].user
        kyc, _ = CourierKYC.objects.get_or_create(user=user)
        kyc.selfie_id_card = validated_data["selfie_id_card"]
        kyc.save(update_fields=["selfie_id_card"])
        return kyc

    def to_representation(self, instance):
        request = self.context.get("request")
        url = instance.selfie_id_card.url if instance.selfie_id_card else None
        if url and request:
            url = request.build_absolute_uri(url)
        return {"selfie_id_card": url}



class RequestCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(validators=[phone_re])

class VerifyCodeSerializer(serializers.Serializer):
    phone = serializers.CharField(validators=[phone_re])
    code  = serializers.CharField(max_length=8)



class ClientProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    first_name = serializers.CharField(source='user.first_name', required=False)
    last_name  = serializers.CharField(source='user.last_name', required=False)
    avatar     = serializers.ImageField(source='user.avatar', required=False, allow_null=True)

    class Meta:
        model = ClientProfile
        fields = ('user', 'first_name', 'last_name', 'avatar', 'created_at')
        read_only_fields = ('created_at',)

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


class CarrierProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    first_name = serializers.CharField(source='user.first_name', required=False)
    last_name  = serializers.CharField(source='user.last_name', required=False)
    avatar     = serializers.ImageField(source='user.avatar', required=False, allow_null=True)

    class Meta:
        model = CarrierProfile
        fields = ('user', 'first_name', 'last_name', 'avatar', 'created_at')
        read_only_fields = ('created_at',)

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
    


def _abs_url(request, file_field):
    if not file_field:
        return None
    url = getattr(file_field, "url", None)
    return request.build_absolute_uri(url) if (request and url) else url


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