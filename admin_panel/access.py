from functools import wraps
from urllib.parse import urlencode

from django.shortcuts import redirect, render


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            query = urlencode({"next": request.get_full_path()})
            return redirect(f"/panel/login/?{query}")
        if not (user.is_staff or user.is_superuser):
            return render(
                request,
                "admin_panel/permission_denied.html",
                status=403,
            )
        return view(request, *args, **kwargs)

    return wrapped
