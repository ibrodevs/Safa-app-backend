from __future__ import annotations
from django.utils import timezone
from rest_framework import generics, permissions, status, serializers, viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiResponse,
    inline_serializer,
)

from .models import FCMToken, Notification
from .serializers import FCMTokenSerializer, NotificationSerializer


@extend_schema(
    tags=["Уведомления"],
    summary="Регистрация FCM-токена устройства",
    request=FCMTokenSerializer,
    responses={
        201: FCMTokenSerializer,
        400: OpenApiResponse(description="Некорректные данные"),
        401: OpenApiResponse(description="Неавторизован"),
    },
)
class FCMRegisterView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FCMTokenSerializer


@extend_schema(
    tags=["Уведомления"],
    summary="Удаление FCM-токена устройства",
    request=inline_serializer(
        name="FCMUnregisterRequest",
        fields={"token": serializers.CharField()},
    ),
    responses={
        204: OpenApiResponse(description="Токен успешно удалён"),
        400: OpenApiResponse(description="token required"),
        401: OpenApiResponse(description="Неавторизован"),
    },
)
class FCMUnregisterView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        token = request.data.get("token")
        if not token:
            return Response({"detail": "token required"}, status=status.HTTP_400_BAD_REQUEST)
        FCMToken.objects.filter(user=request.user, token=token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        tags=["Уведомления"],
        summary="История уведомлений текущего пользователя",
        parameters=[
            OpenApiParameter(
                name="is_read",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Фильтр прочитанности: 0 — непрочитанные, 1 — прочитанные",
                enum=["0", "1"],
            ),
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Номер страницы",
            ),
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Размер страницы",
            ),
        ],
        responses=NotificationSerializer(many=True),
    ),
    retrieve=extend_schema(
        tags=["Уведомления"],
        summary="Детали одного уведомления",
        responses=NotificationSerializer,
    ),
)
class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        is_read = self.request.query_params.get("is_read")
        if is_read == "1":
            qs = qs.filter(is_read=True)
        elif is_read == "0":
            qs = qs.filter(is_read=False)
        return qs.order_by("-created_at")

    @extend_schema(
        tags=["Уведомления"],
        summary="Количество непрочитанных уведомлений",
        responses=inline_serializer(
            name="UnreadCountResponse",
            fields={"unread": serializers.IntegerField()},
        ),
    )
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request, *args, **kwargs):
        count = self.get_queryset().filter(is_read=False).count()
        return Response({"unread": count})

    @extend_schema(
        tags=["Уведомления"],
        summary="Отметить уведомление прочитанным",
        responses=NotificationSerializer,
    )
    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None, *args, **kwargs):
        notif = self.get_object()
        if not notif.is_read:
            notif.is_read = True
            notif.read_at = timezone.now()
            notif.save(update_fields=["is_read", "read_at"])
        return Response(NotificationSerializer(notif).data)
