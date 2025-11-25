from django.urls import path
from .views import *

from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notifications")
urlpatterns = [
    path("register/", FCMRegisterView.as_view(), name="fcm-register"),
    path("unregister/", FCMUnregisterView.as_view(), name="fcm-unregister"),
]
