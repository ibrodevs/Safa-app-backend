from django.core.paginator import Paginator
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from apps.users.models import User

from admin_panel.access import staff_required
from admin_panel.forms import PanelUserForm
from .common import panel_render


def _user_queryset():
    return User.objects.select_related("profile", "kyc").order_by("-created_at")


@staff_required
def user_list(request):
    queryset = _user_queryset().filter(is_staff=False)
    query = request.GET.get("q", "").strip()
    role = request.GET.get("role", "").strip()
    if query:
        filters = Q(first_name__icontains=query) | Q(phone_number__icontains=query)
        if query.isdigit():
            filters |= Q(pk=int(query))
        queryset = queryset.filter(filters)
    if role in User.Roles.values:
        queryset = queryset.filter(role=role)
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return panel_render(
        request,
        "admin_panel/users/list.html",
        {"page": page, "query": query, "selected_role": role},
        section="users",
        title="Пользователи",
    )


def _detail_context(user):
    if user.role == User.Roles.CARRIER:
        orders = user.shipments_as_carrier.select_related("client")[:10]
    else:
        orders = user.shipments_as_client.select_related("carrier")[:10]
    return {"person": user, "orders": orders}


@staff_required
def user_detail(request, pk):
    person = get_object_or_404(_user_queryset(), pk=pk, is_staff=False)
    return panel_render(
        request,
        "admin_panel/users/detail.html",
        _detail_context(person),
        section="users",
        title=person.first_name or person.phone_number,
    )


@staff_required
@require_http_methods(["GET", "POST"])
def user_form(request, pk=None, courier=False):
    person = get_object_or_404(User, pk=pk, is_staff=False) if pk else User()
    initial = {"role": User.Roles.CARRIER} if courier and not pk else None
    form = PanelUserForm(
        request.POST or None,
        request.FILES or None,
        instance=person,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            person = form.save(commit=False)
            if courier:
                person.role = User.Roles.CARRIER
            person.save()
            from apps.users.models import CourierKYC, UserProfile

            UserProfile.objects.get_or_create(user=person)
            if person.role == User.Roles.CARRIER:
                CourierKYC.objects.get_or_create(user=person)
        messages.success(request, "Пользователь сохранён.")
        return redirect(
            "admin_panel:courier_detail" if person.role == User.Roles.CARRIER else "admin_panel:user_detail",
            pk=person.pk,
        )
    return panel_render(
        request,
        "admin_panel/users/form.html",
        {"form": form, "person": person if pk else None, "courier_mode": courier},
        section="couriers" if courier else "users",
        title="Редактирование" if pk else ("Новый специалист" if courier else "Новый пользователь"),
    )


@staff_required
def courier_list(request):
    queryset = _user_queryset().filter(role=User.Roles.CARRIER, is_staff=False)
    query = request.GET.get("q", "").strip()
    specialist_type = request.GET.get("type", "").strip()
    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query) | Q(phone_number__icontains=query)
        )
    if specialist_type in User.SpecialistType.values:
        queryset = queryset.filter(specialist_type=specialist_type)
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return panel_render(
        request,
        "admin_panel/couriers/list.html",
        {
            "page": page,
            "query": query,
            "selected_type": specialist_type,
            "specialist_types": User.SpecialistType.choices,
        },
        section="couriers",
        title="Специалисты",
    )


@staff_required
def courier_detail(request, pk):
    person = get_object_or_404(
        _user_queryset(),
        pk=pk,
        role=User.Roles.CARRIER,
        is_staff=False,
    )
    return panel_render(
        request,
        "admin_panel/users/detail.html",
        _detail_context(person),
        section="couriers",
        title=person.first_name or person.phone_number,
    )
