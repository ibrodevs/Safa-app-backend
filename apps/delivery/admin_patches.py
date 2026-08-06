from __future__ import annotations

from django.contrib import admin

from .map_models import MarketMapRevision
from .models import Bazar


def allow_bazar_map_cascade_deletion() -> None:
    """Allow deleting a bazar together with its map revisions in Django Admin.

    Django Admin requires a separate delete permission for every related model
    shown on the confirmation page. MarketMapRevision is an implementation
    detail of a bazar and already uses CASCADE, so that extra permission should
    not block deleting the bazar itself.
    """

    bazar_admin = admin.site._registry.get(Bazar)
    if bazar_admin is None:
        return

    admin_class = bazar_admin.__class__
    if getattr(admin_class, "_bazar_map_delete_patch_applied", False):
        return

    original_get_deleted_objects = admin_class.get_deleted_objects
    map_verbose_name = str(MarketMapRevision._meta.verbose_name)

    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = original_get_deleted_objects(
            self,
            objs,
            request,
        )
        perms_needed.discard(map_verbose_name)
        return deleted_objects, model_count, perms_needed, protected

    admin_class.get_deleted_objects = get_deleted_objects
    admin_class._bazar_map_delete_patch_applied = True
