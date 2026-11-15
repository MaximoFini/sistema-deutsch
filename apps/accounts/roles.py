"""Roles del panel. Están definidos en código y se sincronizan después de cada migrate.

Cada módulo nuevo agrega acá los permisos que corresponden a cada rol. Los permisos
puntuales por usuario se gestionan desde la pantalla de Usuarios, no acá.
"""

ADMIN = "Administrador"
DEPOSITO = "Depósito"
VENTAS = "Ventas"
VENDEDOR = "Vendedor"

ROLE_PERMISSIONS: dict[str, list[str]] = {
    ADMIN: [
        "accounts.manage_users",
        "audit.view_auditlog",
        "alerts.view_alert",
        "alerts.change_alerttype",
        "integrations.view_status",
        "integrations.retry_event",
        "integrations.toggle_write_switch",
        "integrations.manage_connection",
        "conversations.view_question",
        "conversations.answer_question",
        "conversations.view_message",
        "conversations.send_message",
        "conversations.view_claim",
        "conversations.manage_saved_replies",
        "core.change_source_of_truth",
        "catalog.view_variant",
        "catalog.manage_links",
        "catalog.import_contabilium",
        "catalog.view_channel_stock",
        "catalog.view_quality",
        "catalog.view_listing_health",
        "sales.view_salesdocument",
        "sales.change_order_status",
        "sales.cancel_manual_order",
        "sales.add_manual_order",
        "sales.receive_return",
        "sales.mark_return_adjusted",
        "fulfillment.view_pickbatch",
        "fulfillment.manage_carriers",
        "reports.view_reports",
    ],
    DEPOSITO: [
        "alerts.view_alert",
        "catalog.view_variant",
        "sales.view_salesdocument",
        "sales.change_order_status",
        "sales.receive_return",
        "fulfillment.view_pickbatch",
    ],
    VENTAS: [
        "alerts.view_alert",
        "conversations.view_question",
        "conversations.answer_question",
        "conversations.view_message",
        "conversations.send_message",
        "conversations.view_claim",
        "conversations.manage_saved_replies",
        "catalog.view_variant",
        "catalog.manage_links",
        "catalog.view_channel_stock",
        "catalog.view_quality",
        "catalog.view_listing_health",
        "sales.view_salesdocument",
        "sales.change_order_status",
        "sales.cancel_manual_order",
        "sales.add_manual_order",
        "sales.receive_return",
        "fulfillment.view_pickbatch",
    ],
    VENDEDOR: [
        "alerts.view_alert",
        "catalog.view_variant",
        "sales.view_salesdocument",
        "conversations.view_question",
        "conversations.answer_question",
        "conversations.view_message",
        "conversations.send_message",
    ],
}

ROLE_NAMES = list(ROLE_PERMISSIONS)

# Nombre que ve el administrador en la pantalla de Usuarios (los permisos por defecto de
# Django vienen en inglés: "Can view ...").
PERMISSION_LABELS: dict[str, str] = {
    "accounts.manage_users": "Administrar usuarios, roles y permisos",
    "audit.view_auditlog": "Ver la auditoría",
    "alerts.view_alert": "Ver avisos",
    "alerts.change_alerttype": "Configurar tipos de alerta (destinatarios y email)",
    "integrations.view_status": "Ver el estado de las integraciones",
    "integrations.retry_event": "Reprocesar eventos de integración fallidos",
    "integrations.toggle_write_switch": "Encender o apagar la escritura de stock/precio a un canal",
    "core.change_source_of_truth": "Cambiar la fuente de verdad de un dato",
    "integrations.manage_connection": "Conectar o reconectar un canal de venta",
    "conversations.view_question": "Ver las preguntas de Mercado Libre",
    "conversations.answer_question": "Responder preguntas de Mercado Libre",
    "conversations.view_message": "Ver los mensajes postventa de Mercado Libre",
    "conversations.send_message": "Enviar mensajes postventa",
    "conversations.view_claim": "Ver reclamos y devoluciones",
    "conversations.manage_saved_replies": "Crear y editar respuestas guardadas",
    "catalog.view_variant": "Ver el catálogo",
    "catalog.manage_links": "Vincular publicaciones y códigos con SKU",
    "catalog.import_contabilium": "Importar el archivo de productos de Contabilium",
    "catalog.view_channel_stock": "Ver stock y precio por canal",
    "catalog.view_quality": "Ver el panel de calidad de datos",
    "catalog.view_listing_health": "Ver la salud de las publicaciones de Mercado Libre",
    "sales.view_salesdocument": "Ver pedidos",
    "sales.change_order_status": "Cambiar el estado de los pedidos",
    "sales.cancel_manual_order": "Cancelar pedidos manuales",
    "sales.add_manual_order": "Cargar y editar pedidos manuales",
    "sales.receive_return": "Registrar devoluciones",
    "sales.mark_return_adjusted": "Marcar devoluciones como ajustadas en Contabilium",
    "fulfillment.view_pickbatch": "Ver las tandas de preparación y su hoja de picking",
    "fulfillment.manage_carriers": "Editar la lista de expresos (transportes)",
    "reports.view_reports": "Ver reportes",
}


def sync_roles(using="default"):
    from django.contrib.auth.models import Group, Permission

    for role, perm_names in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.using(using).get_or_create(name=role)
        perms = []
        for name in perm_names:
            app_label, codename = name.split(".")
            perm = (
                Permission.objects.using(using)
                .filter(content_type__app_label=app_label, codename=codename)
                .first()
            )
            if perm is not None:  # si la app aún no migró, se completa en el próximo migrate
                perms.append(perm)
        group.permissions.set(perms)


def _last_project_app_label() -> str:
    from django.apps import apps

    labels = [c.label for c in apps.get_app_configs() if c.name.startswith("apps.")]
    return labels[-1]


def sync_roles_signal(sender, using="default", **kwargs):
    # La señal llega una vez por app, en el orden de INSTALLED_APPS; sincronizamos con la última
    # app propia (hoy `reports`), así ya existen los permisos de todas las apps en el primer migrate.
    if getattr(sender, "label", None) != _last_project_app_label():
        return
    sync_roles(using=using)
