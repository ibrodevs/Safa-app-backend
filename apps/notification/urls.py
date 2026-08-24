from django.urls import path, include
from .views import *

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notifications")
urlpatterns = [
    path("", include(router.urls)),
    path("register/", FCMRegisterView.as_view(), name="fcm-register"),
    path(
        "register-kyc/",
        PendingKYCFCMRegisterView.as_view(),
        name="fcm-register-kyc",
    ),
    path("unregister/", FCMUnregisterView.as_view(), name="fcm-unregister"),
]
