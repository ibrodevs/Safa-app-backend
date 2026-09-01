from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from apps.users.models import User

from admin_panel.access import staff_required
from admin_panel.forms import AdminCreateForm, AdminEditForm, AdminPasswordChangeForm
from .common import panel_render


@staff_required
def admin_list(request):
    queryset = User.objects.filter(is_staff=True).order_by("-created_at")
    query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if query:
        filters = Q(first_name__icontains=query) | Q(phone_number__icontains=query)
        if query.isdigit():
            filters |= Q(pk=int(query))
        queryset = queryset.filter(filters)

    if status_filter == "active":
        queryset = queryset.filter(is_active=True)
    elif status_filter == "inactive":
        queryset = queryset.filter(is_active=False)

    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return panel_render(
        request,
        "admin_panel/admins/list.html",
        {
            "page": page,
            "query": query,
            "selected_status": status_filter,
            "total_admins": User.objects.filter(is_staff=True).count(),
        },
        section="admins",
        title="Администраторы",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def admin_create(request):
    form = AdminCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        admin_user = form.save()
        messages.success(
            request,
            f"Администратор {admin_user.first_name or admin_user.phone_number} успешно добавлен.",
        )
        return redirect("admin_panel:admins")

    return panel_render(
        request,
        "admin_panel/admins/form.html",
        {"form": form, "admin_user": None},
        section="admins",
        title="Новый администратор",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def admin_edit(request, pk):
    admin_user = get_object_or_404(User, pk=pk, is_staff=True)
    form = AdminEditForm(request.POST or None, instance=admin_user)

    if request.method == "POST":
        if form.is_valid():
            # Prevent accidental self-deactivation
            if admin_user.pk == request.user.pk and not form.cleaned_data.get("is_active"):
                form.add_error("is_active", "Вы не можете заблокировать свою собственную учётную запись.")
            else:
                form.save()
                messages.success(
                    request,
                    f"Данные администратора {admin_user.first_name or admin_user.phone_number} сохранены.",
                )
                return redirect("admin_panel:admins")

    return panel_render(
        request,
        "admin_panel/admins/form.html",
        {"form": form, "admin_user": admin_user},
        section="admins",
        title=f"Редактирование: {admin_user.first_name or admin_user.phone_number}",
    )


@staff_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    form = AdminPasswordChangeForm(user=request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        new_password = form.cleaned_data["new_password"]
        request.user.set_password(new_password)
        request.user.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, "Ваш пароль успешно изменён.")
        return redirect("admin_panel:password_change")

    return panel_render(
        request,
        "admin_panel/settings/password_change.html",
        {"form": form},
        section="settings",
        title="Смена пароля",
    )
