from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST


@require_http_methods(["GET", "POST"])
def panel_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("admin_panel:dashboard")
    form = AuthenticationForm(request, data=request.POST or None)
    form.fields["username"].label = "Телефон сотрудника"
    form.fields["username"].widget.attrs.update(
        {"class": "input", "placeholder": "996 XXX XXX XXX", "autofocus": True}
    )
    form.fields["password"].label = "Пароль"
    form.fields["password"].widget.attrs.update(
        {"class": "input", "placeholder": "Введите пароль"}
    )
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if not (user.is_staff or user.is_superuser):
            form.add_error(None, "Доступ разрешён только сотрудникам Safa.")
        else:
            login(request, user)
            next_url = request.POST.get("next", "")
            if not next_url.startswith("/panel/"):
                next_url = "/panel/"
            return redirect(next_url)
    return render(
        request,
        "admin_panel/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@require_POST
def panel_logout(request):
    logout(request)
    return redirect("admin_panel:login")
