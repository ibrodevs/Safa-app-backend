from django.conf import settings

from admin_panel.access import staff_required
from .common import panel_render


@staff_required
def settings_page(request):
    system = {
        "environment": "Разработка" if settings.DEBUG else "Production",
        "timezone": settings.TIME_ZONE,
        "finik": bool(settings.FINIK_API_KEY and settings.FINIK_ACCOUNT_ID),
        "firebase_android": bool(settings.FCM_ANDROID_SERVICE_ACCOUNT_FILE),
        "firebase_ios": bool(settings.FCM_IOS_SERVICE_ACCOUNT_FILE),
    }
    return panel_render(
        request,
        "admin_panel/settings/index.html",
        {"system": system},
        section="settings",
        title="Настройки",
    )
