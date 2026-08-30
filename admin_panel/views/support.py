from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from admin_panel.access import staff_required
from apps.delivery.models import SupportContact
from .common import panel_render


@staff_required
@require_http_methods(["GET", "POST"])
def support_page(request):
    contact = SupportContact.get_solo()

    if request.method == "POST":
        phone = (request.POST.get("phone") or "").strip()
        telegram = (request.POST.get("telegram") or "").strip()
        whatsapp = (request.POST.get("whatsapp") or "").strip()
        working_hours = (request.POST.get("working_hours") or "").strip()
        message = (request.POST.get("message") or "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not phone:
            messages.error(request, "Укажите номер телефона поддержки.")
        else:
            contact.phone = phone
            contact.telegram = telegram or phone
            contact.whatsapp = whatsapp or phone
            contact.working_hours = working_hours or "Ежедневно с 09:00 до 21:00 по Бишкеку."
            contact.message = message or "Если что-то пошло не так — напишите нам или позвоните."
            contact.is_active = is_active
            contact.save()
            messages.success(request, "Настройки службы поддержки успешно сохранены.")
            return redirect("admin_panel:support")

    return panel_render(
        request,
        "admin_panel/support/index.html",
        {"contact": contact},
        section="support",
        title="Служба поддержки",
    )
