
from django.urls import path
from .views import CarrierWalletView, FinikCallbackView, FinikConfigView

urlpatterns = [
    path("finik/callback/", FinikCallbackView.as_view(), name="finik-callback"),
    path("finik/config/", FinikConfigView.as_view(), name="finik-config"),
    path("carrier/wallet/", CarrierWalletView.as_view(), name="carrier-wallet"),
]
