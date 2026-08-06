from django.apps import AppConfig
from django.db import models


class DeleveryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.delivery'

    def ready(self):
        # Модель карты вынесена отдельно, чтобы не раздувать основной models.py.
        # Импорт в ready регистрирует её в приложении delivery и подключает
        # отдельный редактор Django Admin.
        from . import map_models  # noqa: F401
        from . import map_admin  # noqa: F401
        from .models import ShipmentStop
        from .admin_patches import allow_bazar_map_cascade_deletion

        # Контейнер — справочник текущей карты, а остановка заказа хранит
        # собственный снимок title/lat/lon. Поэтому удаление контейнера не должно
        # удалять или блокировать историю заказов: ссылка очищается, снимок остаётся.
        ShipmentStop._meta.get_field("container").remote_field.on_delete = models.SET_NULL

        # Карты базара уже удаляются через CASCADE. Эта настройка убирает только
        # лишнюю проверку отдельного права delete_marketmaprevision в Django Admin.
        allow_bazar_map_cascade_deletion()
