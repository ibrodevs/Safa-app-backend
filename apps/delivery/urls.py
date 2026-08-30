from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from .map_api import PublishedMarketMapView
from .map_reverse_api import SafaReverseGeocodeView

router = DefaultRouter()
router.register("shipments", ShipmentViewSet, basename="shipments")
router.register("bazars", BazarViewSet, basename="bazars")
router.register("passages", PassageViewSet, basename="passages")
router.register("containers", ContainerViewSet, basename="containers")
router.register("amanat/categories", AmanatCategoryViewSet, basename="amanat-categories")
router.register("amanat/campaigns", AmanatCampaignViewSet, basename="amanat-campaigns")

urlpatterns = [
    path("geo/reverse/", SafaReverseGeocodeView.as_view()),
    path("geo/autocomplete/", AutocompleteView.as_view()),
    path("map/features/", PublishedMarketMapView.as_view(), name="published-market-map"),
    path("position/", CourierPositionView.as_view(), name="courier-position"),
    path("stats/", CarrierDailyStatsView.as_view(), name="carrier-daily-stats"),
    path("support/", SupportView.as_view(), name="support"),
    path("privacy/", PrivacyPolicyView.as_view(), name="privacy-policy"),
    path("faq/", FAQListView.as_view(), name="faq-list"),
    path("", include(router.urls)),
]
