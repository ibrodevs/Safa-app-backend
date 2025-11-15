from apps.users.views import *
from rest_framework import routers
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
router = routers.DefaultRouter()




urlpatterns = [
    path("register/", RegisterView.as_view(), name='reg'),
    path('token/', TokenObtainPairView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('debug-code/', DebugRequestCodeView.as_view(), name='debug-code'),
    path("selfie/", SelfieWithIdCardView.as_view(), name="kyc-selfie"),
    path('whatsapp-code', RequestCodeWhatsAppView.as_view(), name='wha_code'),
    path('verify/', VerifyCodeView.as_view(), name='verify'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('profile/<int:pk>', UserProfileView.as_view(), name='profile_id'),
    path("", include(router.urls)),
]

