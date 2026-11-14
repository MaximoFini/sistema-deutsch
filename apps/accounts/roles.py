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
        "core.change_source_of_truth",
    ],
    DEPOSITO: ["alerts.view_alert"],
    VENTAS: ["alerts.view_alert"],
    VENDEDOR: ["alerts.view_alert"],
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


def sync_roles_signal(sender, using="default", **kwargs):
    # La señal llega una vez por app; sincronizamos al final (última app propia).
    if getattr(sender, "label", None) != "integrations":
        return
    sync_roles(using=using)
