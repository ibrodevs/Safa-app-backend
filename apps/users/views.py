from django.shortcuts import render
from rest_framework.generics import GenericAPIView
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
from rest_framework.exceptions import MethodNotAllowed
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


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
        user, created = User.objects.get_or_create(
            phone_number=phone)
        
        if is_static_otp_phone(phone):
            code = static_otp_for(phone)
            detail = "sent_debug_static"
            # Для статик-номеров всегда гарантируем верификацию
            user.is_verify = True
            if not user.first_name:
                user.first_name = "Тестовый Юзер"
            user.save()
            
            CourierKYC.objects.update_or_create(
                user=user, 
                defaults={"status": CourierKYC.Status.APPROVED}
            )
            UserProfile.objects.get_or_create(user=user)
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

        if not is_static_otp_phone(phone):
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

        code = str(ser.validated_data["code"]).strip()

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

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        return Response(
            {
                "detail": "Номер подтверждён",
                "user_id": user.id,
                "is_verify": user.is_verify,
                "access": str(access),
                "refresh": str(refresh),
            },
            status=200,
        )
    

    
@extend_schema(tags=["Профили"])
class UserProfileView(GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserProfileSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = UserProfile.objects.select_related("user")

    def _self_profile(self):
        return UserProfile.objects.select_related("user").get_or_create(user=self.request.user)[0]

    def get_object(self):
        pk = self.kwargs.get("pk")
        if pk is None:
            return self._self_profile()            
        return self.get_queryset().get(pk=pk)     


    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        return Response(self.get_serializer(obj).data)

    def patch(self, request, *args, **kwargs):
        if "pk" in kwargs:
            raise MethodNotAllowed("PATCH")
        obj = self._self_profile()
        ser = self.get_serializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    def put(self, request, *args, **kwargs):
        if "pk" in kwargs:
            raise MethodNotAllowed("PUT")
        obj = self._self_profile()
        ser = self.get_serializer(obj, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)



@extend_schema(
    tags=["Аутентификация"],
    request=SelfieWithIdCardSerializer,
    responses={200: SelfieWithIdCardSerializer, 201: SelfieWithIdCardSerializer},
)
class SelfieWithIdCardView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = SelfieWithIdCardSerializer
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        kyc = serializer.save()
        code = status.HTTP_201_CREATED if not kyc.checked_at else status.HTTP_200_OK
        return Response(
            SelfieWithIdCardSerializer(kyc, context={"request": request}).data,
            status=code,
        )





@extend_schema(
    tags=["Аутентификация"],
    summary="Логин тачкиста по телефону и статусу KYC",
    request=CarrierLoginSerializer,
    responses={
        200: OpenApiResponse(description="Успешный вход, статус approved"),
        403: OpenApiResponse(description="Профиль на проверке или отклонён"),
        404: OpenApiResponse(description="Перевозчик не найден"),
    },
)
class CarrierLoginView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = CarrierLoginSerializer

    def post(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            phone = normalize_phone(ser.validated_data["phone"])
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        try:
            user = User.objects.get(phone_number=phone, role=User.Roles.CARRIER)
        except User.DoesNotExist:
            return Response({"detail": "Перевозчик с таким телефоном не найден."}, status=404)

        kyc = getattr(user, "kyc", None)
        if not kyc:
            return Response(
                {
                    "status": "no_kyc",
                    "detail": "Вы ещё не загрузили документы для проверки.",
                },
                status=403,
            )

        if kyc.status == CourierKYC.Status.PENDING:
            return Response(
                {
                    "status": "pending",
                    "detail": "Ваши данные на проверке.",
                },
                status=403,
            )

        if kyc.status == CourierKYC.Status.REJECTED:
            return Response(
                {
                    "status": "rejected",
                    "detail": "Ваши данные отклонены.",
                    "comment": kyc.comment or "",
                },
                status=403,
            )

        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        return Response(
            {
                "status": "approved",
                "detail": "Профиль одобрен.",
                "user_id": user.id,
                "access": str(access),
                "refresh": str(refresh),
            },
            status=200,
        )





@extend_schema(
    tags=["Аутентификация"],
    summary="Удаление заявки курьера (KYC) и его профиля",
    responses={
        200: OpenApiResponse(description="Заявка и профиль удалены"),
        400: OpenApiResponse(description="Нельзя удалить уже одобренную заявку"),
        403: OpenApiResponse(description="Не курьер"),
        404: OpenApiResponse(description="Заявка не найдена"),
    },
)
class CourierKYCCancelView(generics.GenericAPIView):
    """
    Удаляет заявку (CourierKYC) и профиль (UserProfile) текущего авторизованного курьера.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user

        logger.info(
            "CourierKYC cancel requested",
            extra={
                "user_id": getattr(user, "id", None),
                "phone_number": getattr(user, "phone_number", None),
                "role": getattr(user, "role", None),
            },
        )

        if user.role != User.Roles.CARRIER:
            logger.warning(
                "CourierKYC cancel forbidden: user is not carrier",
                extra={
                    "user_id": getattr(user, "id", None),
                    "role": getattr(user, "role", None),
                },
            )
            raise PermissionDenied("Только перевозчик может удалять свою заявку.")

        kyc = getattr(user, "kyc", None)
        if kyc is None:
            logger.info(
                "CourierKYC cancel: no KYC found for carrier",
                extra={
                    "user_id": user.id,
                    "phone_number": user.phone_number,
                },
            )
            return Response(
                {"detail": "У вас нет активной заявки курьера."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if kyc.status == CourierKYC.Status.APPROVED:
            logger.info(
                "CourierKYC cancel denied: KYC already approved",
                extra={
                    "user_id": user.id,
                    "phone_number": user.phone_number,
                    "kyc_status": kyc.status,
                },
            )
            return Response(
                {
                    "detail": (
                        "Нельзя удалить уже одобренную заявку. "
                        "Свяжитесь с поддержкой, если нужно изменить данные."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # порядок: сначала профиль, затем KYC (или наоборот — не критично, всё в одной транзакции не требуется)
        deleted_profile_count, _ = UserProfile.objects.filter(user=user).delete()
        logger.info(
            "UserProfile deleted for courier (if existed)",
            extra={
                "user_id": user.id,
                "phone_number": user.phone_number,
                "deleted_profile_count": deleted_profile_count,
            },
        )

        kyc.delete()
        logger.info(
            "CourierKYC deleted successfully",
            extra={
                "user_id": user.id,
                "phone_number": user.phone_number,
            },
        )

        return Response(
            {"detail": "Заявка курьера и профиль удалены."},
            status=status.HTTP_200_OK,
        )

@extend_schema(
    tags=["Профили"],
    summary="Удаление собственного аккаунта (Soft Delete)",
    responses={
        200: OpenApiResponse(description="Аккаунт успешно деактивирован"),
        401: OpenApiResponse(description="Не авторизован"),
    },
)
class DeleteAccountView(generics.GenericAPIView):
    """
    Деактивирует аккаунт текущего пользователя, анонимизируя личные данные.
    Это позволяет сохранить целостность базы данных (заказы, платежи).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        old_phone = user.phone_number
        
        logger.info(
            "Account deletion requested (Soft Delete)",
            extra={
                "user_id": user.id,
                "phone_number": old_phone,
            },
        )

        # Анонимизация данных
        user.is_active = False
        user.phone_number = f"del{user.id}"
        user.first_name = "Удаленный пользователь"
        user.email = None
        user.city = None
        user.otp = None
        user.is_verify = False
        
        # Обработка профиля, если он существует
        if hasattr(user, 'profile'):
            profile = user.profile
            profile.rate = 0
            profile.client_rate_count = "0"
            profile.save()

        # Удаление аватара, если есть
        if user.avatar:
            user.avatar.delete(save=False)
            user.avatar = None

        user.save()

        logger.info(
            "Account successfully de-activated/anonymized",
            extra={
                "user_id": user.id,
                "new_phone_placeholder": user.phone_number,
            },
        )

        return Response(
            {"detail": "Ваш аккаунт успешно удален. Благодарим за использование нашего сервиса!"},
            status=status.HTTP_200_OK,
        )
