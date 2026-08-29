from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def health(request):
    result = {"status": "ok", "database": "ok", "channels": "ok"}

    # ── Database ──────────────────────────────────────────────────
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        result["database"] = "unavailable"
        result["status"] = "unavailable"

    # ── Channel layer (Redis in production) ───────────────────────
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        layer = get_channel_layer()
        if layer is not None:
            # InMemoryChannelLayer doesn't support group_send, but a
            # simple send/receive round-trip proves liveness for Redis.
            test_channel = "health-check-ping"
            async_to_sync(layer.send)(test_channel, {"type": "health.ping"})
            async_to_sync(layer.receive)(test_channel)
    except Exception:
        result["channels"] = "unavailable"
        result["status"] = "unavailable"

    status_code = 200 if result["status"] == "ok" else 503
    return JsonResponse(result, status=status_code)
