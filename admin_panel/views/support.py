from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from admin_panel.access import staff_required
from apps.delivery.models import FAQItem, SupportContact
from .common import panel_render


@staff_required
@require_http_methods(["GET", "POST"])
def support_page(request):
    contact = SupportContact.get_solo()

    if request.method == "POST":
        action = request.POST.get("action", "save_contact")

        if action == "save_contact":
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

        elif action == "add_faq":
            question = (request.POST.get("question") or "").strip()
            answer = (request.POST.get("answer") or "").strip()
            sort_order = int(request.POST.get("sort_order") or 0)
            is_active = request.POST.get("is_active") == "on"

            if not question or not answer:
                messages.error(request, "Заполните вопрос и ответ.")
            else:
                FAQItem.objects.create(
                    question=question,
                    answer=answer,
                    sort_order=sort_order,
                    is_active=is_active,
                )
                messages.success(request, f"Вопрос «{question}» добавлен.")
            return redirect("admin_panel:support")

        elif action == "edit_faq":
            faq_id = request.POST.get("faq_id")
            faq = get_object_or_404(FAQItem, id=faq_id)
            question = (request.POST.get("question") or "").strip()
            answer = (request.POST.get("answer") or "").strip()
            sort_order = int(request.POST.get("sort_order") or 0)
            is_active = request.POST.get("is_active") == "on"

            if not question or not answer:
                messages.error(request, "Заполните вопрос и ответ.")
            else:
                faq.question = question
                faq.answer = answer
                faq.sort_order = sort_order
                faq.is_active = is_active
                faq.save()
                messages.success(request, f"Вопрос «{question}» обновлен.")
            return redirect("admin_panel:support")

        elif action == "delete_faq":
            faq_id = request.POST.get("faq_id")
            faq = get_object_or_404(FAQItem, id=faq_id)
            q_title = faq.question
            faq.delete()
            messages.success(request, f"Вопрос «{q_title}» удален.")
            return redirect("admin_panel:support")

    faqs = FAQItem.objects.all().order_by("sort_order", "id")

    return panel_render(
        request,
        "admin_panel/support/index.html",
        {
            "contact": contact,
            "faqs": faqs,
        },
        section="support",
        title="Служба поддержки и FAQ",
    )
