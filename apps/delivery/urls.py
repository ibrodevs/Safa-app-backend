from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register("shipments", ShipmentViewSet, basename="shipments")
router.register(r"geo", GeoViewSet, basename="geo")

urlpatterns = [
    path("api/reverse/", ReverseGeocodeView.as_view()),
    path("", include(router.urls))]
