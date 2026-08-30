from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from admin_panel.access import staff_required
from apps.delivery.models import PrivacyPolicy
from .common import panel_render


@staff_required
@require_http_methods(["GET", "POST"])
def privacy_page(request):
    policy = PrivacyPolicy.get_solo()

    if request.method == "POST":
        content = (request.POST.get("content") or "").strip()
        if not content:
            messages.error(request, "Текст политики конфиденциальности не может быть пустым.")
        else:
            policy.content = content
            policy.save()
            messages.success(request, "Политика конфиденциальности успешно обновлена.")
            return redirect("admin_panel:privacy")

    return panel_render(
        request,
        "admin_panel/privacy/index.html",
        {"policy": policy},
        section="privacy",
        title="Политика конфиденциальности",
    )
