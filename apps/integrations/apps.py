from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = "apps.integrations"
    verbose_name = "Integraciones"

    def ready(self):
        from . import registry

        registry.autodiscover()
