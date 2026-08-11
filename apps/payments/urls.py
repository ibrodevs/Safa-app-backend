
from django.urls import path
from .views import CarrierWalletView, FinikCallbackView

urlpatterns = [
    path("finik/callback/", FinikCallbackView.as_view(), name="finik-callback"),
    path("carrier/wallet/", CarrierWalletView.as_view(), name="carrier-wallet"),
]
