
from django.urls import path
from .views import (
    CarrierWalletView,
    FinikCallbackView,
    FinikConfigView,
    FinikReconcileView,
)

urlpatterns = [
    path("finik/callback/", FinikCallbackView.as_view(), name="finik-callback"),
    path("finik/config/", FinikConfigView.as_view(), name="finik-config"),
    path("finik/reconcile/", FinikReconcileView.as_view(), name="finik-reconcile"),
    path("carrier/wallet/", CarrierWalletView.as_view(), name="carrier-wallet"),
]
