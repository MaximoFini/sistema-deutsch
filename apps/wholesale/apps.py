from django.apps import AppConfig


class WholesaleConfig(AppConfig):
    name = "apps.wholesale"
    verbose_name = "Tienda mayorista"

    def ready(self):
        from apps.sales.signals import order_invoice_changed, order_status_changed

        from .signals import on_invoice_changed, on_status_changed

        order_status_changed.connect(on_status_changed, dispatch_uid="wholesale.on_status_changed")
        order_invoice_changed.connect(on_invoice_changed, dispatch_uid="wholesale.on_invoice_changed")
