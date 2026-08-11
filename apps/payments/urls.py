
from django.urls import path
from .views import FinikCallbackView

urlpatterns = [
    path("finik/callback/", FinikCallbackView.as_view(), name="finik-callback"),
]
