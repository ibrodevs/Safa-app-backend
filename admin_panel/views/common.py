from django.shortcuts import render


def panel_render(request, template, context=None, *, section="", title=""):
    payload = {
        "panel_section": section,
        "page_title": title,
        **(context or {}),
    }
    return render(request, template, payload)
