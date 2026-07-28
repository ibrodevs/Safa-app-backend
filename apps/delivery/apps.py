from django.apps import AppConfig


class DeleveryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.delivery'

    def ready(self):
        # Модель карты вынесена отдельно, чтобы не раздувать основной models.py.
        # Импорт в ready регистрирует её в приложении delivery и подключает
        # отдельный редактор Django Admin.
        from . import map_models  # noqa: F401
        from . import map_admin  # noqa: F401
