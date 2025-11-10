from django.shortcuts import render
from apps.users.models import *
from apps.users.serializers import *
from rest_framework.permissions import AllowAny
from rest_framework import permissions
from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework import viewsets, permissions, status, generics, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from apps.users.otp import *
from django.core.cache import cache
from .otp import generate_otp
from .chatflow import chatflow_send_text, ChatFlowError
from rest_framework.parsers import MultiPartParser, JSONParser, FormParser
from apps.users.utlis import *

@extend_schema(tags=["Аутентификация"])
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]




@extend_schema(tags=["Аутентификация"])
class DebugRequestCodeView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RequestCodeSerializer

    def post(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data["phone"]
        user, _ = User.objects.get_or_create(
            phone_number=phone)
        
        if is_static_otp_phone(phone):
            code = static_otp_for(phone)
            detail = "sent_debug_static"
        else:
            code = generate_otp()
            ttl = getattr(settings, "OTP_TTL_SECONDS", 300)
            cache.set(f"otp:{phone}", {"code": code, "attempts": 0, "sent_at": timezone.now()}, timeout=ttl)
            detail = "sent_debug"

        user.otp = code  
        user.save(update_fields=["otp"])

        return Response({"detail": detail, "phone": phone, "code": code}, status=200)



def _otp_text(code: str) -> str:
    ttl_min = max(1, int(getattr(settings, "OTP_TTL_SECONDS", 300)) // 60)
    return f"Код подтверждения: {code}\nНикому его не сообщайте. Действует {ttl_min} мин."

@extend_schema(tags=["Аутентификация"])
class RequestCodeWhatsAppView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RequestCodeSerializer 

    def post(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            phone = normalize_phone(ser.validated_data["phone"])
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        code = generate_otp(phone=phone)
        cache.set(
            f"otp:{phone}",
            {"code": code, "attempts": 0, "sent_at": timezone.now()},
            timeout=int(getattr(settings, "OTP_TTL_SECONDS", 300)),
        )

        try:
            chatflow_send_text(phone, _otp_text(code)) 
        except ChatFlowError as e:
            cache.delete(f"otp:{phone}")  
            return Response({"detail": f"WhatsApp send failed: {e}"}, status=502)

        return Response({"detail": "sent_whatsapp", "phone": phone}, status=200)
    
@extend_schema(tags=["Аутентификация"])
class VerifyCodeView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = VerifyCodeSerializer 

    def post(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            phone = normalize_phone(ser.validated_data["phone"])
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        code  = str(ser.validated_data["code"]).strip()

        if is_static_otp_phone(phone):
            expected = str(generate_otp(phone=phone))  
            if code != expected:
                return Response({"detail": "Неверный код."}, status=400)

        else:
            cache_key = f"otp:{phone}"
            cached = cache.get(cache_key)
            if not cached:
                return Response({"detail": "Код не найден или истёк."}, status=400)

            attempts = int(cached.get("attempts", 0))
            max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", None)

            if str(cached.get("code")) != code:
                attempts += 1
                cached["attempts"] = attempts
                ttl = int(getattr(settings, "OTP_TTL_SECONDS", 300))
                cache.set(cache_key, cached, timeout=ttl)
                if max_attempts is not None and attempts >= int(max_attempts):
                    cache.delete(cache_key)
                    return Response({"detail": "Превышено число попыток."}, status=400)
                return Response({"detail": "Неверный код."}, status=400)

            cache.delete(cache_key)

        try:
            user = User.objects.get(phone_number=phone)
        except User.DoesNotExist:
            return Response({"detail": "Пользователь не найден."}, status=404)

        if not user.is_verify:
            user.is_verify = True
            user.save(update_fields=["is_verify"])

        return Response({"detail": "Номер подтверждён", "user_id": user.id, "is_verify": user.is_verify}, status=200)
    
class OwnProfileMixin:
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if getattr(self, "action", None) == "list":
            return qs.filter(user=self.request.user)
        return qs

    def get_object(self):
        obj = super().get_object()
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            if obj.user_id != self.request.user.id and not self.request.user.is_staff:
                raise PermissionDenied("Можно изменять только свой профиль.")
        return obj

    @action(detail=False, methods=["get", "patch", "put"])
    def me(self, request):
        Model = self.get_queryset().model
        obj, _ = Model.objects.select_related("user").get_or_create(user=request.user)

        if request.method in ("PATCH", "PUT"):
            serializer = self.get_serializer(obj, data=request.data, partial=(request.method == "PATCH"))
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        return Response(self.get_serializer(obj).data)


@extend_schema(tags=["Профили"])
class ClientProfileView(
    OwnProfileMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ClientProfile.objects.select_related("user")
    serializer_class = ClientProfileSerializer


@extend_schema(tags=["Профили"])
class CarrierProfileView(
    OwnProfileMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = CarrierProfile.objects.select_related("user")
    serializer_class = CarrierProfileSerializer




@extend_schema(tags=["Аутентификация"])
class SelfieWithIdCardView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SelfieWithIdCardSerializer
    parser_classes = (MultiPartParser, FormParser)

    @extend_schema(
        request=SelfieWithIdCardSerializer,
        responses={
            201: SelfieWithIdCardSerializer,
            200: SelfieWithIdCardSerializer,
            403: OpenApiResponse(description="Только для перевозчиков"),
        },
    )
    def post(self, request, *args, **kwargs):
        if request.user.role != User.Roles.CARRIER:
            return Response({"detail": "Только для перевозчиков."}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        kyc = serializer.save()
        code = status.HTTP_201_CREATED if not kyc.checked_at else status.HTTP_200_OK
        return Response(SelfieWithIdCardSerializer(kyc, context={"request": request}).data, status=code)

    @extend_schema(responses={200: SelfieWithIdCardSerializer, 403: OpenApiResponse(description="Только для перевозчиков")})
    def get(self, request, *args, **kwargs):
        if request.user.role != User.Roles.CARRIER:
            return Response({"detail": "Только для перевозчиков."}, status=status.HTTP_403_FORBIDDEN)

        kyc, _ = CourierKYC.objects.get_or_create(user=request.user)
        return Response(SelfieWithIdCardSerializer(kyc, context={"request": request}).data, status=status.HTTP_200_OK)