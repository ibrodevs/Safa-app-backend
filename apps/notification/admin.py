from django.contrib import admin
from django.utils import timezone

from .events import broadcast_to_role
from .models import RoleBroadcast


@admin.register(RoleBroadcast)
class RoleBroadcastAdmin(admin.ModelAdmin):
    list_display = ("title", "role", "app", "sent_at", "sent_count")
    readonly_fields = ("created_at", "sent_at", "sent_count")
    fields = (
        "title",
        "body",
        "app",
        "role",
        "channel",
        "deep_link",
        "silent",
        "created_at",
        "sent_at",
        "sent_count",
    )

    def save_model(self, request, obj, form, change):
        # A saved broadcast is immutable from a delivery perspective. Previously
        # every later edit/save sent it to the whole role again.
        already_sent = bool(obj.sent_at)
        super().save_model(request, obj, form, change)
        if already_sent:
            return

        delivered_count = broadcast_to_role(
            role=obj.role,
            app=obj.app,
            title=obj.title,
            body=obj.body,
            channel=obj.channel,
            deep_link=obj.deep_link,
            type_="manual",
            silent=obj.silent,
        )

        obj.sent_at = timezone.now()
        obj.sent_count = delivered_count
        obj.save(update_fields=["sent_at", "sent_count"])
