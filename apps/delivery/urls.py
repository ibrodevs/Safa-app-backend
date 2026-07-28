from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from .map_api import PublishedMarketMapView

router = DefaultRouter()
router.register("shipments", ShipmentViewSet, basename="shipments")
router.register("bazars", BazarViewSet, basename="bazars")
router.register("passages", PassageViewSet, basename="passages")
router.register("containers", ContainerViewSet, basename="containers")

urlpatterns = [
    path("geo/reverse/", ReverseGeocodeView.as_view()),
    path("geo/autocomplete/", AutocompleteView.as_view()),
    path("map/features/", PublishedMarketMapView.as_view(), name="published-market-map"),
    path("stats/", CarrierDailyStatsView.as_view(), name="carrier-daily-stats"),
    path("support/", SupportView.as_view(), name="support"),
    path("", include(router.urls)),
]
