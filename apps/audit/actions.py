"""Catálogo de acciones auditadas. Cada módulo registra las suyas con `audit.record`.

El texto es lo que ve el administrador en la pantalla de Auditoría.
"""

ACTIONS: dict[str, str] = {
    # M0 · usuarios y sistema
    "user.created": "Usuario creado",
    "user.updated": "Usuario editado",
    "user.deactivated": "Usuario desactivado",
    "user.reactivated": "Usuario reactivado",
    "source_of_truth.changed": "Fuente de verdad cambiada",
    "integration.write_switch_changed": "Interruptor de escritura cambiado",
    "integration.write_blocked": "Escritura a canal bloqueada",
    "integration.event_retried": "Evento de integración reprocesado",
    "integration.connected": "Canal conectado",
    "integration.disconnected": "Canal desconectado",
    "privacy.customer_redacted": "Datos de cliente anonimizados (pedido de privacidad)",
    "alert_type.updated": "Tipo de alerta editado",
    # M4 · pedidos
    "order.status_changed": "Cambio de estado de pedido",
    "order.manual_created": "Pedido manual creado",
    "order.returned": "Devolución registrada",
    # M6 · Mercado Libre
    "ml.question_answered": "Respuesta a pregunta de ML",
    "ml.message_sent": "Mensaje enviado en ML",
    "ml.listing_edited": "Publicación editada",
    # M8 · mayorista
    "client.approved": "Cliente mayorista aprobado",
    "client.rejected": "Cliente mayorista rechazado",
    "payment.confirmed": "Pago confirmado",
}


def label(action: str) -> str:
    return ACTIONS.get(action, action)
