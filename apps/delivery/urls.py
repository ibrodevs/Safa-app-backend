from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register("shipments", ShipmentViewSet, basename="shipments")
router.register("segments", CourierSegmentViewSet, basename="segments")

urlpatterns = [
    path("geo/reverse/", ReverseGeocodeView.as_view()),
    path("geo/autocomplete/",   AutocompleteView.as_view()),
    path("stats/", CarrierDailyStatsView.as_view(), name="carrier-daily-stats"),
    path("", include(router.urls))]
