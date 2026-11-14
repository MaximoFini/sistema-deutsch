from django.apps import AppConfig


class FulfillmentConfig(AppConfig):
    name = "apps.fulfillment"
    verbose_name = "Preparación y despacho"

    def ready(self):
        from apps.sales.signals import order_status_changed

        from .batches import on_status_changed_signal

        order_status_changed.connect(on_status_changed_signal, dispatch_uid="fulfillment.on_status_changed")
