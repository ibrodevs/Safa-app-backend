from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register("shipments", ShipmentViewSet, basename="shipments")
router.register(r"geo", GeoViewSet, basename="geo")
urlpatterns = [path("", include(router.urls))]
