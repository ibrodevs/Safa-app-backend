from django.contrib import admin
from django.utils import timezone

from .models import RoleBroadcast
from .events import broadcast_to_role


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
        super().save_model(request, obj, form, change)

        cnt = broadcast_to_role(
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
        obj.sent_count = cnt
        obj.save(update_fields=["sent_at", "sent_count"])
