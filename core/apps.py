from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Oficina'

    def ready(self):
        from . import audit  # noqa: F401  (conecta os signals de histórico)
